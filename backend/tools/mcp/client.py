from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import aiohttp


MCP_PROTOCOL_VERSION = "2025-11-25"


class MCPClientError(RuntimeError):
    """MCP client error."""


class MCPProtocolError(MCPClientError):
    """MCP protocol error."""


class MCPTransport(ABC):
    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def send(self, message: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def receive(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class StdioMCPTransport(MCPTransport):
    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.process: Optional[subprocess.Popen[bytes]] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr_buffer: list[str] = []

    async def start(self) -> None:
        if self.process is not None:
            return
        self.process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            cwd=self.cwd,
        )
        self._stderr_buffer = []
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        while True:
            line = await asyncio.to_thread(process.stderr.readline)
            if not line:
                return
            text = line.decode("utf-8", errors="ignore")
            self._stderr_buffer.append(text)
            if len(self._stderr_buffer) > 200:
                self._stderr_buffer = self._stderr_buffer[-200:]

    async def send(self, message: Dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPClientError("stdio transport not started")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

        def _write() -> None:
            assert self.process is not None and self.process.stdin is not None
            self.process.stdin.write(payload)
            self.process.stdin.flush()

        await asyncio.to_thread(_write)

    async def receive(self) -> Dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise MCPClientError("stdio transport not started")

        while True:
            line = await asyncio.to_thread(self.process.stdout.readline)
            if not line:
                stderr_output = ''.join(self._stderr_buffer).strip()
                raise MCPClientError(f"stdio transport closed unexpectedly: {stderr_output}")

            payload = line.decode("utf-8").strip()
            if not payload:
                continue

            try:
                message = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if isinstance(message, dict):
                return message

    async def close(self) -> None:
        if self.process is None:
            return

        process = self.process
        self.process = None

        if process.stdin is not None:
            process.stdin.close()

        if process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)

        stderr_task = self._stderr_task
        self._stderr_task = None
        if stderr_task is not None:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass

        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


class StreamableHTTPMCPTransport(MCPTransport):
    def __init__(self, endpoint: str, headers: dict[str, str] | None = None, timeout: int = 30):
        self.endpoint = endpoint
        self.headers = headers or {}
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self._incoming: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

    async def send(self, message: Dict[str, Any]) -> None:
        if self.session is None:
            raise MCPClientError("HTTP transport not started")
        async with self.session.post(self.endpoint, json=message, headers=self.headers) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                async for raw_line in response.content:
                    line = raw_line.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload:
                        await self._incoming.put(json.loads(payload))
            else:
                await self._incoming.put(await response.json())

    async def receive(self) -> Dict[str, Any]:
        return await self._incoming.get()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None


class MCPClientSession:
    def __init__(self, transport: MCPTransport, timeout: int = 30, client_name: str = "personal-agent"):
        self.transport = transport
        self.timeout = timeout
        self.client_name = client_name
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}

    async def start(self) -> None:
        await self.transport.start()
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def _reader_loop(self) -> None:
        while True:
            try:
                message = await self.transport.receive()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(error)
                self._pending.clear()
                return

            request_id = message.get("id")
            if request_id is not None and request_id in self._pending:
                future = self._pending.pop(request_id)
                if not future.done():
                    future.set_result(message)

    async def request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await self.start()
        self._request_id += 1
        request_id = self._request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self.transport.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            }
        )
        try:
            response = await asyncio.wait_for(future, timeout=self.timeout)
        except Exception:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            raise
        if "error" in response:
            error = response["error"] or {}
            raise MCPProtocolError(error.get("message") or f"MCP request failed: {method}")
        return response.get("result", {})

    async def notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        await self.start()
        await self.transport.send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        )

    async def initialize(self) -> Dict[str, Any]:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": self.client_name, "version": "1.0.0"},
            },
        )
        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.request("tools/list")
        tools = result.get("tools")
        return tools if isinstance(tools, list) else []

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )

    async def close(self) -> None:
        reader_task = self._reader_task
        self._reader_task = None

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

        await self.transport.close()

        if reader_task is not None:
            reader_task.cancel()
            try:
                if reader_task.get_loop() is asyncio.get_running_loop():
                    await reader_task
            except asyncio.CancelledError:
                pass
            except RuntimeError:
                pass


def build_stdio_transport_from_config(server_config: dict[str, Any]) -> StdioMCPTransport:
    command = server_config.get("command") or sys.executable
    args = list(server_config.get("args") or [])
    module = server_config.get("module")
    if module:
        args = ["-m", module, *args]
    return StdioMCPTransport(
        command=command,
        args=args,
        env=server_config.get("env"),
        cwd=server_config.get("cwd"),
    )

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from urllib.parse import urljoin
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp

from backend.infrastructure.mcp.protocol import MCP_PROTOCOL_VERSION


class MCPClientError(RuntimeError):
    """MCP 客户端基础异常。"""


class MCPTransport(ABC):
    """MCP transport 抽象。"""

    @abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def receive(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class StdioMCPTransport(MCPTransport):
    """基于 stdio 的 MCP transport。"""

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
        process_env = os.environ.copy()
        if self.env:
            process_env.update({key: str(value) for key, value in self.env.items()})
        self.process = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=process_env,
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

    async def send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise MCPClientError("stdio transport not started")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")

        def _write() -> None:
            assert self.process is not None and self.process.stdin is not None
            self.process.stdin.write(payload)
            self.process.stdin.flush()

        await asyncio.to_thread(_write)

    async def receive(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise MCPClientError("stdio transport not started")

        while True:
            line = await asyncio.to_thread(self.process.stdout.readline)
            if not line:
                stderr_output = "".join(self._stderr_buffer).strip()
                raise MCPClientError(f"stdio transport closed unexpectedly: {stderr_output}")

            try:
                payload = line.decode("utf-8").strip()
            except UnicodeDecodeError as error:
                stderr_output = "".join(self._stderr_buffer).strip()
                raise MCPClientError(
                    "stdio transport received non-UTF-8 payload; "
                    "MCP stdio servers must emit UTF-8 JSON lines. "
                    f"stderr: {stderr_output}"
                ) from error
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
    """基于 streamable HTTP 的 MCP transport。"""

    def __init__(self, endpoint: str, headers: dict[str, str] | None = None, timeout: int = 30):
        self.endpoint = endpoint
        self.headers = headers or {}
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._session_id: Optional[str] = None
        self._protocol_version = MCP_PROTOCOL_VERSION
        self._stream_task: Optional[asyncio.Task] = None
        self._stream_endpoint: Optional[str] = None

    async def start(self) -> None:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout))

    def _build_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        headers.setdefault("Accept", "application/json, text/event-stream")
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("MCP-Protocol-Version", self._protocol_version)
        if self._session_id:
            headers.setdefault("MCP-Session-Id", self._session_id)
        return headers

    def _capture_response_headers(self, response: aiohttp.ClientResponse) -> None:
        session_id = response.headers.get("MCP-Session-Id")
        if session_id:
            self._session_id = session_id

        protocol_version = response.headers.get("MCP-Protocol-Version")
        if protocol_version:
            self._protocol_version = protocol_version

    async def _enqueue_json_payload(self, payload_text: str) -> None:
        text = payload_text.strip()
        if not text:
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise MCPClientError(f"Invalid MCP HTTP response payload: {error}") from error
        if isinstance(payload, dict):
            await self._incoming.put(payload)

    async def _consume_event_stream(self, response: aiohttp.ClientResponse) -> None:
        data_lines: list[str] = []
        async for raw_line in response.content:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if data_lines:
                    await self._enqueue_json_payload("\n".join(data_lines))
                    data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if data_lines:
            await self._enqueue_json_payload("\n".join(data_lines))

    def _build_event_stream_headers(self) -> dict[str, str]:
        """构建事件流监听头，避免对 GET 请求携带无意义的 Content-Type。"""

        headers = self._build_headers()
        headers["Accept"] = "text/event-stream, application/json"
        headers.pop("Content-Type", None)
        return headers

    def _resolve_stream_endpoint(self, response: aiohttp.ClientResponse) -> str:
        """优先使用服务端返回的 Location，其次回退到原始 endpoint。"""

        location = response.headers.get("Location") or response.headers.get("location")
        if not location:
            return self.endpoint
        return urljoin(str(response.url), location)

    async def _listen_event_stream(self, stream_endpoint: str) -> None:
        if self.session is None:
            raise MCPClientError("HTTP transport not started")

        timeout = aiohttp.ClientTimeout(total=None, sock_connect=self.timeout)
        try:
            async with self.session.get(stream_endpoint, headers=self._build_event_stream_headers(), timeout=timeout) as response:
                self._capture_response_headers(response)
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" in content_type:
                    await self._consume_event_stream(response)
                    return

                payload_text = await response.text()
                await self._enqueue_json_payload(payload_text)
        except asyncio.CancelledError:
            raise
        except aiohttp.ClientError as error:
            raise MCPClientError(f"MCP HTTP event stream failed: {error}") from error

    async def _ensure_event_stream_listener(self, stream_endpoint: str) -> None:
        existing_task = self._stream_task
        if existing_task is not None and not existing_task.done() and self._stream_endpoint == stream_endpoint:
            return

        self._stream_endpoint = stream_endpoint
        self._stream_task = asyncio.create_task(self._listen_event_stream(stream_endpoint))

    async def send(self, message: dict[str, Any]) -> None:
        if self.session is None:
            raise MCPClientError("HTTP transport not started")

        async with self.session.post(self.endpoint, json=message, headers=self._build_headers()) as response:
            self._capture_response_headers(response)

            if response.status in {202, 204}:
                await response.read()
                await self._ensure_event_stream_listener(self._resolve_stream_endpoint(response))
                return

            content_type = response.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                await self._consume_event_stream(response)
                return

            payload_text = await response.text()
            await self._enqueue_json_payload(payload_text)

    async def receive(self) -> dict[str, Any]:
        return await self._incoming.get()

    async def close(self) -> None:
        stream_task = self._stream_task
        self._stream_task = None
        self._stream_endpoint = None
        if stream_task is not None:
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass
            except MCPClientError:
                pass

        if self.session and not self.session.closed:
            if self._session_id:
                try:
                    await self.session.delete(self.endpoint, headers=self._build_headers())
                except aiohttp.ClientError:
                    pass
            await self.session.close()
        self.session = None
        self._session_id = None
        self._protocol_version = MCP_PROTOCOL_VERSION


def build_stdio_transport_from_config(server_config: dict[str, Any]) -> StdioMCPTransport:
    """根据配置构建 stdio transport。"""

    command = server_config.get("command") or sys.executable
    args = list(server_config.get("args") or [])
    module = server_config.get("module")
    configured_env = server_config.get("env") or {}
    env = {key: str(value) for key, value in configured_env.items()} if isinstance(configured_env, dict) else {}
    if module:
        args = ["-X", "utf8", "-m", module, *args]
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
    return StdioMCPTransport(
        command=command,
        args=args,
        env=env,
        cwd=server_config.get("cwd"),
    )

from __future__ import annotations

import asyncio
from inspect import isawaitable
from typing import Any, Callable, Optional

from backend.infrastructure.mcp.protocol import MCP_PROTOCOL_VERSION
from backend.infrastructure.mcp.transport import MCPClientError, MCPTransport


class MCPProtocolError(MCPClientError):
    """MCP 协议错误。"""

    def __init__(self, message: str, *, code: Optional[int] = None, data: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


NotificationHandler = Callable[[dict[str, Any]], Any]
RequestHandler = Callable[[str, dict[str, Any]], Any]


class MCPClientSession:
    """统一 MCP 客户端会话。"""

    def __init__(
        self,
        transport: MCPTransport,
        timeout: int = 30,
        client_name: str = "personal-agent",
        notification_handler: Optional[NotificationHandler] = None,
        request_handler: Optional[RequestHandler] = None,
    ):
        self.transport = transport
        self.timeout = timeout
        self.client_name = client_name
        self.notification_handler = notification_handler
        self.request_handler = request_handler
        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._notification_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.server_info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}

    @staticmethod
    async def _await_if_needed(value: Any) -> Any:
        if isawaitable(value):
            return await value
        return value

    async def start(self) -> None:
        await self.transport.start()
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._reader_loop())

    async def _send_server_response(self, request_id: Any, *, result: Any = None, error: Optional[dict[str, Any]] = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result if result is not None else {}
        await self.transport.send(payload)

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        await self._notification_queue.put(message)
        if self.notification_handler is not None:
            await self._await_if_needed(self.notification_handler(message))

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if request_id is None or not isinstance(method, str):
            return

        try:
            if self.request_handler is None:
                await self._send_server_response(
                    request_id,
                    error={"code": -32601, "message": f"Method not supported by MCP client: {method}"},
                )
                return

            result = await self._await_if_needed(self.request_handler(method, params))
            await self._send_server_response(request_id, result=result)
        except MCPProtocolError as error:
            await self._send_server_response(
                request_id,
                error={
                    "code": error.code or -32000,
                    "message": str(error),
                    "data": error.data or None,
                },
            )
        except Exception as error:
            await self._send_server_response(
                request_id,
                error={"code": -32000, "message": f"MCP client request handler error: {error}"},
            )

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
                continue

            method = message.get("method")
            if not isinstance(method, str):
                continue

            if request_id is None:
                await self._handle_notification(message)
            else:
                await self._handle_server_request(message)

    async def request(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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
        self._validate_response_message(response, method)
        if "error" in response:
            error = response["error"] or {}
            raise MCPProtocolError(
                error.get("message") or f"MCP request failed: {method}",
                code=error.get("code"),
                data=error.get("data") if isinstance(error.get("data"), dict) else None,
            )
        return response.get("result", {})

    @staticmethod
    def _validate_response_message(response: dict[str, Any], method: str) -> None:
        """校验响应报文的最小 JSON-RPC 结构，避免静默吞掉协议错误。"""

        if not isinstance(response, dict):
            raise MCPProtocolError(f"Invalid MCP response for {method}: payload must be object")

        jsonrpc_version = response.get("jsonrpc")
        if jsonrpc_version not in {None, "2.0"}:
            raise MCPProtocolError(
                f"Invalid MCP response for {method}: unsupported jsonrpc version {jsonrpc_version}",
                code=-32600,
            )

        if "result" not in response and "error" not in response:
            raise MCPProtocolError(f"Invalid MCP response for {method}: missing result or error", code=-32600)

    async def notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        await self.start()
        await self.transport.send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }
        )

    async def initialize(self) -> dict[str, Any]:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": self.client_name, "version": "1.0.0"},
            },
        )
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version:
            raise MCPProtocolError("MCP initialize response missing protocolVersion", code=-32600)

        server_info = result.get("serverInfo")
        if server_info is not None and not isinstance(server_info, dict):
            raise MCPProtocolError("MCP initialize response serverInfo must be object", code=-32600)

        capabilities = result.get("capabilities")
        if capabilities is not None and not isinstance(capabilities, dict):
            raise MCPProtocolError("MCP initialize response capabilities must be object", code=-32600)

        self.server_info = result.get("serverInfo") or {}
        self.capabilities = result.get("capabilities") or {}
        await self.notify("notifications/initialized")
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.request("tools/list")
        tools = result.get("tools")
        if tools is None:
            return []
        if not isinstance(tools, list):
            raise MCPProtocolError("MCP tools/list response tools must be array", code=-32600)

        normalized_tools: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                raise MCPProtocolError("MCP tools/list item must be object", code=-32600)
            tool_name = tool.get("name")
            if not isinstance(tool_name, str) or not tool_name:
                raise MCPProtocolError("MCP tools/list item missing valid name", code=-32600)
            normalized_tools.append(tool)
        return normalized_tools

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        result = await self.request(
            "tools/call",
            {
                "name": name,
                "arguments": arguments or {},
            },
        )
        if not isinstance(result, dict):
            raise MCPProtocolError(f"MCP tools/call response for {name} must be object", code=-32600)
        return result

    async def next_notification(self) -> dict[str, Any]:
        return await self._notification_queue.get()

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

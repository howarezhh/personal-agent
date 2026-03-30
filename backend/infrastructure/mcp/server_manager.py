from __future__ import annotations

import asyncio
from threading import Lock
from types import MethodType
from typing import Any, Optional

from backend.infrastructure.mcp.client import MCPClientSession
from backend.infrastructure.mcp.transport import StreamableHTTPMCPTransport, build_stdio_transport_from_config


class MCPServerManager:
    """统一管理 MCP server 连接。"""

    def __init__(self):
        # 中文说明：共享连接池按事件循环 + server + timeout 隔离，避免短超时污染长超时工具。
        self._clients: dict[tuple[int, str, int], MCPClientSession] = {}
        self._client_ref_counts: dict[tuple[int, str, int], int] = {}
        self._ephemeral_clients: dict[int, list[MCPClientSession]] = {}
        self._lock = Lock()

    def _remove_ephemeral_client(self, client: MCPClientSession) -> None:
        loop_id = self._loop_id()
        with self._lock:
            session_group = self._ephemeral_clients.get(loop_id, [])
            self._ephemeral_clients[loop_id] = [item for item in session_group if item is not client]
            if not self._ephemeral_clients[loop_id]:
                self._ephemeral_clients.pop(loop_id, None)

    def _wrap_ephemeral_client_close(self, client: MCPClientSession) -> MCPClientSession:
        if getattr(client, "_manager_wrapped_close", False):
            return client

        original_close = client.close
        manager = self

        async def _managed_close(self: MCPClientSession) -> None:
            manager._remove_ephemeral_client(self)
            await original_close()

        client.close = MethodType(_managed_close, client)
        setattr(client, "_manager_wrapped_close", True)
        return client

    @staticmethod
    def _loop_id() -> int:
        return id(asyncio.get_running_loop())

    @staticmethod
    def _make_key(server_name: str, timeout: int) -> tuple[int, str, int]:
        return MCPServerManager._loop_id(), server_name, int(timeout)

    @staticmethod
    async def _build_client(server_name: str, server_config: dict[str, Any], timeout: int = 30) -> MCPClientSession:
        transport_type = server_config.get("transport", "stdio")
        if transport_type == "stdio":
            transport = build_stdio_transport_from_config(server_config)
        elif transport_type in {"streamable_http", "http"}:
            endpoint = server_config.get("endpoint")
            if not endpoint:
                raise ValueError(f"MCP server {server_name} missing endpoint")
            transport = StreamableHTTPMCPTransport(
                endpoint=endpoint,
                headers=server_config.get("headers") or {},
                timeout=timeout,
            )
        else:
            raise ValueError(f"Unsupported MCP transport: {transport_type}")

        client = MCPClientSession(transport=transport, timeout=timeout, client_name="personal-agent")
        await client.initialize()
        return client

    async def connect(self, server_name: str, server_config: dict[str, Any], timeout: int = 30) -> MCPClientSession:
        key = self._make_key(server_name, timeout)
        with self._lock:
            existing = self._clients.get(key)
            if existing is not None:
                self._client_ref_counts[key] = self._client_ref_counts.get(key, 0) + 1
                return existing

        client = await self._build_client(server_name, server_config, timeout=timeout)
        with self._lock:
            existing = self._clients.get(key)
            if existing is not None:
                self._client_ref_counts[key] = self._client_ref_counts.get(key, 0) + 1
                close_extra_client = client
                client = existing
            else:
                self._clients[key] = client
                self._client_ref_counts[key] = 1
                close_extra_client = None

        if close_extra_client is not None:
            await close_extra_client.close()
        return client

    async def open_session(self, server_name: str, server_config: dict[str, Any], timeout: int = 30) -> MCPClientSession:
        client = await self._build_client(server_name, server_config, timeout=timeout)
        client = self._wrap_ephemeral_client_close(client)
        with self._lock:
            self._ephemeral_clients.setdefault(self._loop_id(), []).append(client)
        return client

    async def disconnect(self, server_name: str, timeout: int = 30) -> None:
        key = self._make_key(server_name, timeout)
        client: Optional[MCPClientSession] = None
        with self._lock:
            ref_count = self._client_ref_counts.get(key, 0)
            if ref_count > 1:
                self._client_ref_counts[key] = ref_count - 1
                return
            self._client_ref_counts.pop(key, None)
            client = self._clients.pop(key, None)
        if client is not None:
            await client.close()

    async def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            session_groups = list(self._ephemeral_clients.values())
            self._clients.clear()
            self._client_ref_counts.clear()
            self._ephemeral_clients.clear()

        for session_group in session_groups:
            clients.extend(session_group)

        deduplicated: list[MCPClientSession] = []
        seen_ids: set[int] = set()
        for client in clients:
            client_id = id(client)
            if client_id in seen_ids:
                continue
            seen_ids.add(client_id)
            deduplicated.append(client)

        await asyncio.gather(*(client.close() for client in deduplicated), return_exceptions=True)


_mcp_server_manager: Optional[MCPServerManager] = None


def get_mcp_server_manager() -> MCPServerManager:
    global _mcp_server_manager
    if _mcp_server_manager is None:
        _mcp_server_manager = MCPServerManager()
    return _mcp_server_manager

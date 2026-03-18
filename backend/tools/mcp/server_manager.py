from __future__ import annotations

import asyncio
from typing import Any, Optional

from backend.tools.mcp.client import MCPClientSession, StreamableHTTPMCPTransport, build_stdio_transport_from_config


class MCPServerManager:
    def __init__(self):
        self._clients: dict[tuple[int, str], MCPClientSession] = {}
        self._ephemeral_clients: dict[int, list[MCPClientSession]] = {}

    @staticmethod
    def _loop_id() -> int:
        return id(asyncio.get_running_loop())


    @staticmethod
    def _make_key(server_name: str) -> tuple[int, str]:
        return MCPServerManager._loop_id(), server_name

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
        key = self._make_key(server_name)
        if key in self._clients:
            return self._clients[key]

        client = await self._build_client(server_name, server_config, timeout=timeout)
        self._clients[key] = client
        return client

    async def open_session(self, server_name: str, server_config: dict[str, Any], timeout: int = 30) -> MCPClientSession:
        client = await self._build_client(server_name, server_config, timeout=timeout)
        self._ephemeral_clients.setdefault(self._loop_id(), []).append(client)
        return client

    async def disconnect(self, server_name: str) -> None:
        key = self._make_key(server_name)
        client = self._clients.pop(key, None)
        if client is not None:
            await client.close()

    async def close_all(self) -> None:
        clients = list(self._clients.values())
        for session_group in self._ephemeral_clients.values():
            clients.extend(session_group)
        self._clients.clear()
        self._ephemeral_clients.clear()

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

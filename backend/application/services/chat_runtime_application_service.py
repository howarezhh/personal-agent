from __future__ import annotations

import asyncio
from typing import Any

from backend.core.config_manager import get_config_manager


_active_chat_streams: dict[str, dict[str, Any]] = {}
_active_chat_streams_lock = asyncio.Lock()


class ChatRuntimeApplicationService:
    def get_history_limit(self) -> int:
        history_config = get_config_manager().get_conversation_history_config()
        raw_limit = history_config.get("max_history_length", 10)
        try:
            return max(1, int(raw_limit))
        except (TypeError, ValueError):
            return 10

    async def pause_stream(self, *, stream_id: str, user_id: str) -> dict[str, Any]:
        async with _active_chat_streams_lock:
            stream_context = _active_chat_streams.get(stream_id)
            if not stream_context:
                return {
                    "exists": False,
                    "authorized": True,
                    "paused": False,
                    "task": None,
                }

            if stream_context.get("user_id") != user_id:
                return {
                    "exists": True,
                    "authorized": False,
                    "paused": False,
                    "task": None,
                }

            stream_context["paused"] = True
            return {
                "exists": True,
                "authorized": True,
                "paused": True,
                "task": stream_context.get("task"),
            }

    async def register_stream(
        self,
        *,
        stream_id: str,
        user_id: str,
        conversation_id: str,
        message_id: str,
        task: asyncio.Task[Any] | None,
    ) -> None:
        async with _active_chat_streams_lock:
            _active_chat_streams[stream_id] = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "task": task,
                "paused": False,
            }

    async def cleanup_stream(self, *, stream_id: str) -> None:
        async with _active_chat_streams_lock:
            _active_chat_streams.pop(stream_id, None)

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from backend.database.database_manager import get_database_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class ContentGenerationRecordStore:
    def __init__(self, database_manager=None):
        self.database_manager = database_manager or get_database_manager()

    def execute_db_write(self, query: str, params: tuple[Any, ...]) -> None:
        if hasattr(self.database_manager, "execute_update"):
            self.database_manager.execute_update(query, params)
            return

        execute_query = getattr(self.database_manager, "execute_query", None)
        if not callable(execute_query):
            raise AttributeError("Database manager does not support write execution")

        try:
            execute_query(query, params, fetch_one=False, fetch_all=False)
        except TypeError:
            try:
                execute_query(query, params, fetch=False)
            except TypeError:
                execute_query(query, params)

    async def save_generation(
        self,
        *,
        user_id: str,
        content_type: str,
        action: str,
        input_params: dict,
        tool_name: str,
        conversation_id: Optional[str] = None,
    ) -> tuple[str, int]:
        generation_id = str(uuid.uuid4())
        start_time = int(time.time() * 1000)

        try:
            self.execute_db_write(
                """
                INSERT INTO content_generations
                (id, user_id, conversation_id, content_type, action, input_params, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    generation_id,
                    user_id,
                    conversation_id,
                    content_type,
                    action,
                    json.dumps(input_params, ensure_ascii=False),
                    "pending",
                ),
            )
            logger.info(
                "Created content generation record: generation_id=%s content_type=%s action=%s tool=%s",
                generation_id,
                content_type,
                action,
                tool_name,
            )
        except Exception as error:
            logger.error("Failed to create content generation record: %s", error, exc_info=True)

        return generation_id, start_time

    async def update_generation_result(
        self,
        *,
        generation_id: str,
        start_time_ms: int,
        result: dict,
    ) -> None:
        execution_time = int(time.time() * 1000) - start_time_ms

        try:
            if result.get("success"):
                self.execute_db_write(
                    """
                    UPDATE content_generations
                    SET output_content = %s,
                        status = %s,
                        execution_time = %s
                    WHERE id = %s
                    """,
                    (
                        json.dumps(result.get("data"), ensure_ascii=False),
                        "completed",
                        execution_time,
                        generation_id,
                    ),
                )
                logger.info(
                    "Content generation completed: generation_id=%s execution_time_ms=%s",
                    generation_id,
                    execution_time,
                )
                return

            self.execute_db_write(
                """
                UPDATE content_generations
                SET status = %s,
                    error_message = %s,
                    execution_time = %s
                WHERE id = %s
                """,
                (
                    "failed",
                    result.get("error"),
                    execution_time,
                    generation_id,
                ),
            )
            logger.info(
                "Content generation failed: generation_id=%s error=%s",
                generation_id,
                result.get("error"),
            )
        except Exception as error:
            logger.error("Failed to update content generation record: %s", error, exc_info=True)

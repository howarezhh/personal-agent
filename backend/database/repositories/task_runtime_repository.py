from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from backend.contracts.task_runtime import (
    TaskArtifact,
    TaskCheckpoint,
    TaskExecutionRecord,
    TaskRuntimeState,
)
from backend.database.database_manager import get_database_manager
from backend.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class TaskRuntimePersistenceSnapshot:
    """任务运行时持久化快照。

    该对象作为应用层读取仓储后的统一载体，避免应用层自行拼装多表结果。
    """

    record: TaskExecutionRecord
    state: TaskRuntimeState
    latest_checkpoint: TaskCheckpoint | None
    artifacts: list[TaskArtifact]


class TaskRuntimeRepository:
    """任务运行时仓储。

    说明：
    - `task_runtime_executions` 保存当前最新执行态与完整状态快照。
    - `task_runtime_checkpoints` 保存阶段性检查点，支持恢复与审计。
    - `task_runtime_artifacts` 保存标准产物索引，便于前端任务中心直接读取。
    """

    EXECUTION_TABLE = "task_runtime_executions"
    CHECKPOINT_TABLE = "task_runtime_checkpoints"
    ARTIFACT_TABLE = "task_runtime_artifacts"

    def __init__(self, database_manager=None) -> None:
        self.database_manager = database_manager or get_database_manager()

    def save_execution(
        self,
        *,
        record: TaskExecutionRecord,
        state: TaskRuntimeState,
        user_input: str,
    ) -> None:
        """写入或更新当前任务执行记录。"""
        state_payload = self._serialize_model(state)
        goal_payload = self._serialize_model(state.goal)
        plan_payload = self._serialize_model(state.current_plan) if state.current_plan is not None else None
        termination_payload = self._serialize_model(state.termination) if state.termination is not None else None
        evaluation_payload = (
            self._serialize_model(state.evaluation_report) if state.evaluation_report is not None else None
        )
        metadata_payload = self._serialize_json(record.metadata)

        sql = f"""
            INSERT INTO {self.EXECUTION_TABLE}
            (
                task_id,
                request_id,
                execution_id,
                user_id,
                conversation_id,
                message_id,
                user_input,
                status,
                current_plan_id,
                current_step_id,
                checkpoint_id,
                goal_json,
                current_plan_json,
                state_json,
                termination_json,
                evaluation_report_json,
                metadata_json,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                request_id = VALUES(request_id),
                execution_id = VALUES(execution_id),
                user_id = VALUES(user_id),
                conversation_id = VALUES(conversation_id),
                message_id = VALUES(message_id),
                user_input = VALUES(user_input),
                status = VALUES(status),
                current_plan_id = VALUES(current_plan_id),
                current_step_id = VALUES(current_step_id),
                checkpoint_id = VALUES(checkpoint_id),
                goal_json = VALUES(goal_json),
                current_plan_json = VALUES(current_plan_json),
                state_json = VALUES(state_json),
                termination_json = VALUES(termination_json),
                evaluation_report_json = VALUES(evaluation_report_json),
                metadata_json = VALUES(metadata_json),
                updated_at = VALUES(updated_at)
        """
        params = (
            record.task_id,
            record.request_id,
            record.execution_id,
            record.user_id,
            record.conversation_id,
            record.message_id,
            user_input,
            record.status,
            record.current_plan_id,
            record.current_step_id,
            record.checkpoint_id,
            goal_payload,
            plan_payload,
            state_payload,
            termination_payload,
            evaluation_payload,
            metadata_payload,
            record.created_at,
            record.updated_at,
        )
        self.database_manager.execute_update(sql, params)
        self.replace_artifacts(task_id=record.task_id, artifacts=state.artifacts)

    def create_checkpoint(self, *, checkpoint: TaskCheckpoint, state: TaskRuntimeState) -> None:
        """创建新的任务检查点快照。"""
        sql = f"""
            INSERT INTO {self.CHECKPOINT_TABLE}
            (
                checkpoint_id,
                task_id,
                execution_id,
                status,
                iteration_count,
                completed_step_ids_json,
                latest_plan_id,
                latest_step_id,
                checkpoint_reason,
                state_json,
                metadata_json,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            checkpoint.checkpoint_id,
            checkpoint.task_id,
            checkpoint.execution_id,
            checkpoint.status,
            checkpoint.iteration_count,
            self._serialize_json(checkpoint.completed_step_ids),
            checkpoint.latest_plan_id,
            checkpoint.latest_step_id,
            checkpoint.checkpoint_reason,
            self._serialize_model(state),
            self._serialize_json(checkpoint.metadata),
            checkpoint.created_at,
        )
        self.database_manager.execute_update(sql, params)

    def get_snapshot(self, *, task_id: str) -> TaskRuntimePersistenceSnapshot | None:
        """读取任务当前最新快照。"""
        execution_sql = f"SELECT * FROM {self.EXECUTION_TABLE} WHERE task_id = %s LIMIT 1"
        execution_row = self.database_manager.execute_query(execution_sql, (task_id,), fetch_one=True)
        if not execution_row:
            return None

        record = self._build_execution_record(execution_row)
        state = TaskRuntimeState.model_validate(self._deserialize_json(execution_row.get("state_json"), default={}))
        latest_checkpoint = self.get_latest_checkpoint(task_id=task_id)
        artifacts = self.list_artifacts(task_id=task_id)
        state.artifacts = artifacts
        return TaskRuntimePersistenceSnapshot(
            record=record,
            state=state,
            latest_checkpoint=latest_checkpoint,
            artifacts=artifacts,
        )

    def get_latest_checkpoint(self, *, task_id: str) -> TaskCheckpoint | None:
        """读取任务最新检查点。"""
        sql = f"""
            SELECT *
            FROM {self.CHECKPOINT_TABLE}
            WHERE task_id = %s
            ORDER BY created_at DESC, checkpoint_id DESC
            LIMIT 1
        """
        row = self.database_manager.execute_query(sql, (task_id,), fetch_one=True)
        if not row:
            return None
        return TaskCheckpoint(
            checkpoint_id=row["checkpoint_id"],
            task_id=row.get("task_id"),
            execution_id=row.get("execution_id"),
            status=row.get("status") or "pending",
            iteration_count=int(row.get("iteration_count") or 0),
            completed_step_ids=self._deserialize_json(row.get("completed_step_ids_json"), default=[]),
            latest_plan_id=row.get("latest_plan_id"),
            latest_step_id=row.get("latest_step_id"),
            checkpoint_reason=row.get("checkpoint_reason") or "",
            created_at=row.get("created_at") or "",
            metadata=self._deserialize_json(row.get("metadata_json"), default={}),
        )

    def replace_artifacts(self, *, task_id: str, artifacts: list[TaskArtifact]) -> None:
        """以当前状态为准覆盖任务产物索引。"""
        delete_sql = f"DELETE FROM {self.ARTIFACT_TABLE} WHERE task_id = %s"
        self.database_manager.execute_update(delete_sql, (task_id,))

        if not artifacts:
            return

        insert_sql = f"""
            INSERT INTO {self.ARTIFACT_TABLE}
            (
                artifact_id,
                task_id,
                artifact_type,
                title,
                content_json,
                source_plan_id,
                source_step_id,
                metadata_json,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        for artifact in artifacts:
            self.database_manager.execute_update(
                insert_sql,
                (
                    artifact.artifact_id,
                    task_id,
                    artifact.artifact_type,
                    artifact.title,
                    self._serialize_json(artifact.content),
                    artifact.source_plan_id,
                    artifact.source_step_id,
                    self._serialize_json(artifact.metadata),
                    artifact.created_at,
                ),
            )

    def list_artifacts(self, *, task_id: str) -> list[TaskArtifact]:
        """列出任务产物。"""
        sql = f"""
            SELECT *
            FROM {self.ARTIFACT_TABLE}
            WHERE task_id = %s
            ORDER BY created_at ASC, artifact_id ASC
        """
        rows = self.database_manager.execute_query(sql, (task_id,)) or []
        artifacts: list[TaskArtifact] = []
        for row in rows:
            artifacts.append(
                TaskArtifact(
                    artifact_id=row["artifact_id"],
                    artifact_type=row.get("artifact_type") or "custom",
                    title=row.get("title") or "",
                    content=self._deserialize_json(row.get("content_json")),
                    source_plan_id=row.get("source_plan_id"),
                    source_step_id=row.get("source_step_id"),
                    created_at=row.get("created_at") or "",
                    metadata=self._deserialize_json(row.get("metadata_json"), default={}),
                )
            )
        return artifacts

    def _build_execution_record(self, row: dict[str, Any]) -> TaskExecutionRecord:
        """将数据库行还原为任务执行摘要契约。"""
        return TaskExecutionRecord(
            task_id=row["task_id"],
            request_id=row["request_id"],
            execution_id=row["execution_id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            message_id=row.get("message_id"),
            status=row.get("status") or "pending",
            current_plan_id=row.get("current_plan_id"),
            current_step_id=row.get("current_step_id"),
            checkpoint_id=row.get("checkpoint_id"),
            created_at=row.get("created_at") or "",
            updated_at=row.get("updated_at") or "",
            metadata=self._deserialize_json(row.get("metadata_json"), default={}),
        )

    @staticmethod
    def _serialize_model(model: Any) -> str:
        """统一序列化 Pydantic 模型。"""
        if model is None:
            return "null"
        if hasattr(model, "model_dump"):
            return json.dumps(model.model_dump(), ensure_ascii=False, default=str)
        return json.dumps(model, ensure_ascii=False, default=str)

    @staticmethod
    def _serialize_json(payload: Any) -> str:
        """统一序列化任意 JSON 结构。"""
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _deserialize_json(payload: Any, default: Any = None) -> Any:
        """统一反序列化 JSON 文本。

        数据库驱动有时会直接返回字典对象，因此这里兼容两种输入形态。
        """
        if payload in (None, ""):
            return [] if default == [] else ({} if default == {} else default)
        if isinstance(payload, (dict, list)):
            return payload
        return json.loads(payload)


_task_runtime_repository: TaskRuntimeRepository | None = None


def get_task_runtime_repository() -> TaskRuntimeRepository:
    """获取任务运行时仓储单例。"""
    global _task_runtime_repository
    if _task_runtime_repository is None:
        _task_runtime_repository = TaskRuntimeRepository()
    return _task_runtime_repository

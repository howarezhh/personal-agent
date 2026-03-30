from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from backend.application.task_runtime.event_translator import TaskRuntimeEventTranslator
from backend.application.task_runtime.task_controller import TaskController
from backend.contracts.errors import ErrorCode, bad_request, not_found
from backend.contracts.task_runtime import (
    TaskArtifact,
    TaskCheckpoint,
    TaskControllerRequest,
    TaskExecutionRecord,
    TaskLifecycleAction,
    TaskRuntimePreparation,
    TaskRuntimeState,
)
from backend.database.repositories.task_runtime_repository import (
    TaskRuntimePersistenceSnapshot,
    TaskRuntimeRepository,
)
from backend.utils.logger import get_logger


# 预处理会话缓存键。
#
# 五元组的顺序分别为：
# 1. user_id：当前用户标识，用于隔离不同用户的请求。
# 2. request_id：同一次请求链路的唯一标识。
# 3. conversation_id：所属会话标识，避免不同会话串用缓存。
# 4. user_input：用户原始输入文本，避免相同 request_id 下请求体变化造成误复用。
# 5. metadata_fingerprint：业务补充元数据的稳定指纹，进一步区分不同上下文。
TaskRuntimeSessionCacheKey = tuple[str, str, str, str, str]


@dataclass
class PreparedTaskRuntimeSession:
    """缓存单次 task-runtime 预处理结果。

    设计目的：
    - `prepare_task()` 与 `stream_task_events()` 往往会先后调用；
    - 两者都需要一份“已经完成预处理”的运行时状态；
    - 若每次都重新 prepare，会导致计划重复生成、状态不一致，甚至重复写入消息。

    因此这里把预处理阶段生成的控制器请求与运行时状态缓存下来，
    在 TTL 有效期内允许后续流式执行阶段直接复用。
    """

    # 控制器入参对象，保存 task controller 执行所需的完整链路信息。
    controller_request: TaskControllerRequest
    # 预处理后得到的运行时状态快照，包含 goal、plan、metadata 等核心信息。
    prepared_state: TaskRuntimeState
    # 使用 monotonic 时间记录缓存写入时刻，便于做 TTL 过期判断。
    prepared_at_monotonic: float


@dataclass
class TaskRuntimeStatusSnapshot:
    """任务状态聚合结果。

    这是任务中心查询时对多个持久化对象的聚合视图：
    - `record`：执行记录摘要，适合列表页或状态页快速展示；
    - `state`：完整运行时状态，保留任务内部过程信息；
    - `latest_checkpoint`：最近一次检查点，便于恢复、排障与生命周期操作。
    """

    # 持久化的任务执行记录摘要。
    record: TaskExecutionRecord
    # 当前任务的完整运行时状态。
    state: TaskRuntimeState
    # 最近一次检查点；当尚未生成检查点时可能为空。
    latest_checkpoint: TaskCheckpoint | None


class TaskRuntimeApplicationService:
    """任务运行时应用服务。

    该服务位于 Application 层，负责把“任务运行时”相关能力组织成稳定用例，主要职责包括：
    - 接收上层请求并构造 `TaskControllerRequest`；
    - 调用 `TaskController` 完成预处理、流式执行、生命周期变更；
    - 通过 `TaskRuntimeEventTranslator` 把内部事件翻译为统一 SSE 输出；
    - 按需调用仓储完成执行记录、状态、检查点、产物的持久化；
    - 在持久化能力缺失时自动降级，避免影响主流程。
    """

    def __init__(
        self,
        *,
        task_controller: TaskController,
        event_translator: TaskRuntimeEventTranslator,
        task_runtime_repository: TaskRuntimeRepository | None = None,
        chat_service_support: Any | None = None,
        prepared_session_ttl_seconds: int = 300,
        time_provider: Callable[[], float] | None = None,
    ) -> None:
        # logger：当前应用服务专用日志器，便于按类名聚合排查问题。
        self.logger = get_logger(self.__class__.__name__)
        # task_controller：任务控制器，承载 prepare / stream / lifecycle 等核心编排能力。
        self.task_controller = task_controller
        # event_translator：负责把控制器事件翻译成对外统一的 SSE 文本事件。
        self.event_translator = event_translator
        # task_runtime_repository：任务运行时仓储，负责落库执行记录、状态、检查点与产物。
        self.task_runtime_repository = task_runtime_repository
        # 任务运行时持久化属于可选增强能力：当运行时表缺失时自动降级，避免阻断主聊天链路。
        self._task_runtime_persistence_degraded = False
        # chat_service_support：聊天服务适配对象，用于补充用户/助手消息持久化。
        self.chat_service_support = chat_service_support
        # prepared_session_ttl_seconds：预处理缓存有效期，最小强制为 1 秒，防止非法配置导致缓存失效。
        self.prepared_session_ttl_seconds = max(1, int(prepared_session_ttl_seconds))
        # _time_provider：可注入时间函数，默认使用 monotonic，便于测试时控制时间流逝。
        self._time_provider = time_provider or time.monotonic
        # 使用 user_id / request_id / conversation_id / user_input / 业务 metadata 指纹隔离缓存，
        # 避免不同用户或不同请求体仅因 request_id 相同而串用准备结果。
        self._prepared_sessions: dict[TaskRuntimeSessionCacheKey, PreparedTaskRuntimeSession] = {}
        # 预处理缓存是共享内存结构，异步场景下需要加锁，避免并发读写冲突。
        self._prepared_sessions_lock = asyncio.Lock()

    async def prepare_task(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_input: str,
        message_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRuntimePreparation:
        """准备任务并返回初始 goal / plan，同时缓存该结果供 stream 复用。

        参数说明：
        - `user_id`：当前请求所属用户 ID。
        - `conversation_id`：当前会话 ID。
        - `user_input`：用户输入的原始文本。
        - `message_id`：前端或上游传入的消息 ID，可为空，空时内部自动生成。
        - `request_id`：链路请求 ID，可为空，空时内部自动生成。
        - `metadata`：业务透传元数据，用于补充执行上下文。

        核心逻辑：
        1. 先尝试复用已缓存的 prepare 结果，避免重复生成计划；
        2. 若无缓存则创建新的控制器请求并执行 prepare；
        3. 从预处理状态中抽取对外需要的最小准备结果返回给调用方。
        """
        session = await self._get_or_create_prepared_session(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input=user_input,
            message_id=message_id,
            request_id=request_id,
            metadata=metadata,
        )
        # prepared_state：prepare 阶段产出的运行时状态，是后续 stream 与状态查询的基础。
        prepared_state = session.prepared_state
        if prepared_state.current_plan is None:
            raise RuntimeError("任务运行时未生成初始计划")
        # 这里显式把内部状态映射为对外契约 `TaskRuntimePreparation`，
        # 避免 API 层直接感知完整状态对象，保持契约边界稳定。
        return TaskRuntimePreparation(
            task_id=prepared_state.task_id,
            request_id=session.controller_request.request_id or "",
            execution_id=session.controller_request.execution_id or "",
            status=prepared_state.status,
            checkpoint_id=prepared_state.checkpoint_id,
            goal=prepared_state.goal,
            plan=prepared_state.current_plan,
            evaluation_report=prepared_state.evaluation_report,
            created_at=prepared_state.created_at,
            updated_at=prepared_state.updated_at,
            metadata=dict(prepared_state.metadata),
        )

    async def stream_task_events(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_input: str,
        message_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """流式输出统一 SSE 事件，并在结束后补齐助手消息持久化。

        该方法是任务执行主入口之一，返回值是一个异步生成器，
        上层可以直接把每个字符串当作 SSE event 数据向前端推送。

        核心逻辑：
        - 复用 prepare 阶段缓存，保证计划与执行上下文一致；
        - 将控制器产生的内部事件翻译成统一 SSE 文本；
        - 在流结束后尝试提取最终输出并补充助手消息持久化；
        - 无论成功或失败，都清理本次预处理缓存，避免脏状态长期驻留。
        """
        session = await self._get_or_create_prepared_session(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input=user_input,
            message_id=message_id,
            request_id=request_id,
            metadata=metadata,
        )
        # controller_request：本次任务执行的统一控制器请求对象。
        controller_request = session.controller_request
        # prepared_state：预处理阶段准备好的状态对象，会在整个流式过程中被持续更新。
        prepared_state = session.prepared_state
        # 在正式开始输出流之前，先把任务状态切换为 running，并记录启动检查点。
        await self._set_task_status(prepared_state, controller_request, status="running", checkpoint_reason="stream_started")

        try:
            # 逐个消费控制器事件：每来一个事件，就先尝试持久化进度，再翻译为 SSE 输出。
            async for event in self._iterate_controller_stream(
                prepared_state,
                state_probe=self._build_state_probe(),
            ):
                await self._persist_runtime_progress(
                    prepared_state,
                    controller_request,
                    checkpoint_reason=f"event:{event.stage}",
                    force_checkpoint=event.stage in {"step_observation", "goal_evaluation", "replan", "termination"},
                )
                yield self.event_translator.format_sse(event)

            # 流式正常结束时，强制写入最终检查点，确保任务中心可看到最终状态。
            await self._persist_runtime_progress(
                prepared_state,
                controller_request,
                checkpoint_reason="stream_finished",
                force_checkpoint=True,
            )
            # 最终输出稳定后，再补写助手消息，避免把中间态内容错误落库。
            await self._persist_assistant_message_if_needed(prepared_state, controller_request)
        except Exception as error:
            # 任何未捕获异常都统一转为 failed，并输出标准错误事件给前端。
            self.logger.error("Task runtime stream failed: %s", error, exc_info=True)
            prepared_state.status = "failed"
            await self._persist_runtime_progress(
                prepared_state,
                controller_request,
                checkpoint_reason="stream_error",
                force_checkpoint=True,
            )
            yield self.event_translator.format_error(
                error_message=f"任务执行失败：{error}",
                request_id=controller_request.request_id,
                conversation_id=controller_request.conversation_id,
                message_id=controller_request.message_id,
                execution_id=controller_request.execution_id,
                error_code=ErrorCode.WORKFLOW_EXECUTION_ERROR.value,
            )
        finally:
            # 无论成功或失败，都移除 prepare 缓存，防止旧状态影响下一次执行。
            await self._remove_prepared_session(self._build_session_cache_key(controller_request))

    async def stream_task_events_by_task_id(
        self,
        *,
        user_id: str,
        task_id: str,
    ) -> AsyncGenerator[str, None]:
        """基于已持久化的任务状态继续流式执行。

        适用场景：
        - 前一次任务已落库，但 SSE 连接中断；
        - 用户从任务中心恢复一个尚未结束的任务；
        - 任务执行上下文需要从持久化快照而非内存缓存恢复。

        核心逻辑是：先按 `task_id + user_id` 读取并校验快照，
        再重建 `TaskControllerRequest`，最后从已保存状态继续推进控制器流。
        """
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        controller_request = self._build_controller_request_from_snapshot(snapshot)
        await self._set_task_status(snapshot.state, controller_request, status="running", checkpoint_reason="stream_resumed")

        try:
            async for event in self._iterate_controller_stream(
                snapshot.state,
                state_probe=self._build_state_probe(),
            ):
                await self._persist_runtime_progress(
                    snapshot.state,
                    controller_request,
                    checkpoint_reason=f"event:{event.stage}",
                    force_checkpoint=event.stage in {"step_observation", "goal_evaluation", "replan", "termination"},
                )
                yield self.event_translator.format_sse(event)

            await self._persist_runtime_progress(
                snapshot.state,
                controller_request,
                checkpoint_reason="stream_resumed_finished",
                force_checkpoint=True,
            )
            await self._persist_assistant_message_if_needed(snapshot.state, controller_request)
        finally:
            # 无论成功或失败，都移除 prepare 缓存，防止旧状态影响下一次执行。
            await self._remove_prepared_session(self._build_session_cache_key(controller_request))

    async def get_task_status(self, *, user_id: str, task_id: str) -> TaskRuntimeStatusSnapshot:
        """读取任务当前状态快照。"""
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        return TaskRuntimeStatusSnapshot(
            record=snapshot.record,
            state=snapshot.state,
            latest_checkpoint=snapshot.latest_checkpoint,
        )

    async def pause_task(
        self,
        *,
        user_id: str,
        task_id: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionRecord:
        """暂停任务，后续可通过 resume + stream 恢复。"""
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        if snapshot.record.status in {"succeeded", "cancelled", "timed_out"}:
            raise bad_request("当前任务状态不支持暂停")
        await self._apply_lifecycle_action(
            snapshot=snapshot,
            action="pause",
            reason=reason,
            metadata=metadata,
            next_status="paused",
        )
        return snapshot.record

    async def resume_task(
        self,
        *,
        user_id: str,
        task_id: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionRecord:
        """恢复任务到待运行状态，真正执行由 stream 接口触发。"""
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        if snapshot.record.status not in {"paused", "failed", "pending"}:
            raise bad_request("当前任务状态不支持恢复")
        self._clear_terminal_state(snapshot.state)
        await self._apply_lifecycle_action(
            snapshot=snapshot,
            action="resume",
            reason=reason,
            metadata=metadata,
            next_status="pending",
        )
        return snapshot.record

    async def cancel_task(
        self,
        *,
        user_id: str,
        task_id: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionRecord:
        """取消任务。

        取消属于终止性动作，通常用于用户主动放弃当前任务。
        取消后状态会持久化为终止结果，便于审计与任务中心展示。
        """
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        if snapshot.record.status in {"succeeded", "cancelled"}:
            raise bad_request("当前任务状态不支持取消")
        await self._apply_lifecycle_action(
            snapshot=snapshot,
            action="cancel",
            reason=reason,
            metadata=metadata,
            next_status="cancelled",
        )
        return snapshot.record

    async def retry_task(
        self,
        *,
        user_id: str,
        task_id: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskExecutionRecord:
        """重试任务，保留既有上下文并清理终止态。"""
        snapshot = self._require_task_snapshot(task_id=task_id, user_id=user_id)
        if snapshot.record.status == "succeeded":
            raise bad_request("已成功完成的任务不支持重试")
        self._clear_terminal_state(snapshot.state)
        await self._apply_lifecycle_action(
            snapshot=snapshot,
            action="retry",
            reason=reason,
            metadata=metadata,
            next_status="pending",
        )
        return snapshot.record

    async def _get_or_create_prepared_session(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_input: str,
        message_id: str | None,
        request_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> PreparedTaskRuntimeSession:
        """统一准备并缓存单次请求状态，避免 `/tasks` 与 `/tasks/stream` 各自重复生成。"""
        controller_request = self._build_controller_request(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input=user_input,
            message_id=message_id,
            request_id=request_id,
            metadata=metadata,
        )

        session_cache_key = self._build_session_cache_key(controller_request)
        cached_session = await self._get_prepared_session(session_cache_key)
        if cached_session is not None:
            return cached_session

        self._validate_task_request(user_id=user_id, conversation_id=conversation_id, user_input=user_input, metadata=controller_request.metadata)
        self._persist_user_message(controller_request)

        prepared_state = await self.task_controller.prepare(controller_request)
        if self.task_runtime_repository is not None and hasattr(prepared_state, "goal"):
            self._bootstrap_runtime_state(prepared_state, controller_request)
            self._ensure_state_artifacts(prepared_state)
            await self._persist_runtime_progress(
                prepared_state,
                controller_request,
                checkpoint_reason="prepared",
                force_checkpoint=True,
            )
        session = PreparedTaskRuntimeSession(
            controller_request=controller_request,
            prepared_state=prepared_state,
            prepared_at_monotonic=self._time_provider(),
        )
        await self._store_prepared_session(session_cache_key, session)
        return session

    def _validate_task_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        user_input: str,
        metadata: dict[str, Any],
    ) -> None:
        """复用聊天支持层完成会话归属与知识库归属校验。"""
        if self.chat_service_support is None:
            return

        conversation, _ = self.chat_service_support.ensure_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            question=user_input,
        )
        if conversation is None:
            raise not_found(
                "会话不存在或无权访问",
                error_code=ErrorCode.CONVERSATION_NOT_FOUND,
                error="ConversationNotFound",
            )

        knowledge_base_id = metadata.get("knowledge_base_id")
        if not knowledge_base_id:
            return

        knowledge_base = self.chat_service_support.ensure_knowledge_base(
            user_id=user_id,
            knowledge_base_id=str(knowledge_base_id),
        )
        if knowledge_base is None:
            raise not_found(
                "知识库不存在或无权访问",
                error_code=ErrorCode.KNOWLEDGE_BASE_NOT_FOUND,
                error="KnowledgeBaseNotFound",
            )

    def _persist_user_message(self, controller_request: TaskControllerRequest) -> None:
        """复用聊天支持层持久化用户消息，并保证相同 `message_id` 幂等。"""
        if self.chat_service_support is None:
            return

        self.chat_service_support.save_user_message(
            conversation_id=controller_request.conversation_id,
            question=controller_request.user_input,
            message_id=controller_request.message_id,
            metadata={
                "request_id": controller_request.request_id,
                "execution_id": controller_request.execution_id,
                "conversation_id": controller_request.conversation_id,
                "knowledge_base_id": controller_request.metadata.get("knowledge_base_id"),
            },
        )

    async def _persist_assistant_message_if_needed(
        self,
        prepared_state: TaskRuntimeState,
        controller_request: TaskControllerRequest,
    ) -> None:
        """任务成功完成后复用聊天支持层持久化助手答复。"""
        if self.chat_service_support is None:
            return
        if prepared_state.termination is None or prepared_state.termination.status != "completed":
            return

        final_output = self._extract_latest_final_output(prepared_state)
        if not final_output:
            return

        citations = self._extract_latest_citations(prepared_state)
        self.chat_service_support.save_assistant_message(
            conversation_id=controller_request.conversation_id,
            content=final_output,
            citations=citations,
            parent_message_id=controller_request.message_id,
            metadata={
                "request_id": controller_request.request_id,
                "execution_id": controller_request.execution_id,
            },
        )

    async def _get_prepared_session(
        self,
        session_cache_key: TaskRuntimeSessionCacheKey | None,
    ) -> PreparedTaskRuntimeSession | None:
        if session_cache_key is None:
            return None
        async with self._prepared_sessions_lock:
            self._purge_expired_prepared_sessions_locked()
            return self._prepared_sessions.get(session_cache_key)

    async def _store_prepared_session(
        self,
        session_cache_key: TaskRuntimeSessionCacheKey | None,
        session: PreparedTaskRuntimeSession,
    ) -> None:
        """缓存已准备好的会话，供紧随其后的 stream 调用复用。"""
        if session_cache_key is None:
            return
        async with self._prepared_sessions_lock:
            self._purge_expired_prepared_sessions_locked()
            self._prepared_sessions[session_cache_key] = session

    async def _remove_prepared_session(self, session_cache_key: TaskRuntimeSessionCacheKey | None) -> None:
        if session_cache_key is None:
            return
        async with self._prepared_sessions_lock:
            self._prepared_sessions.pop(session_cache_key, None)

    def _purge_expired_prepared_sessions_locked(self) -> None:
        """惰性清理过期 prepare 缓存，避免只调 `/tasks` 时长期滞留内存。"""
        current_monotonic = self._time_provider()
        expired_cache_keys = [
            session_cache_key
            for session_cache_key, session in self._prepared_sessions.items()
            if self._is_session_expired(session, current_monotonic)
        ]
        for session_cache_key in expired_cache_keys:
            self._prepared_sessions.pop(session_cache_key, None)

    def _is_session_expired(
        self,
        session: PreparedTaskRuntimeSession,
        current_monotonic: float | None = None,
    ) -> bool:
        """判断单个 prepare 缓存是否已超过 TTL。"""
        now_monotonic = current_monotonic if current_monotonic is not None else self._time_provider()
        return (now_monotonic - session.prepared_at_monotonic) >= float(self.prepared_session_ttl_seconds)

    @staticmethod
    def _build_session_cache_key(controller_request: TaskControllerRequest) -> TaskRuntimeSessionCacheKey | None:
        """构造预处理缓存键，确保只在同一真实请求上下文内复用。"""
        if not controller_request.request_id:
            return None
        return (
            controller_request.user_id,
            controller_request.request_id,
            controller_request.conversation_id,
            controller_request.user_input,
            TaskRuntimeApplicationService._build_session_metadata_fingerprint(controller_request),
        )

    @staticmethod
    def _build_session_metadata_fingerprint(controller_request: TaskControllerRequest) -> str:
        """仅提取客户端业务 metadata 指纹，避免内部 trace 字段破坏复用语义。"""
        internal_trace_keys = {"request_id", "message_id", "conversation_id", "execution_id"}
        reusable_metadata = {
            key: value
            for key, value in (controller_request.metadata or {}).items()
            if key not in internal_trace_keys
        }
        return json.dumps(reusable_metadata, sort_keys=True, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_latest_final_output(prepared_state: TaskRuntimeState) -> str:
        """优先读取控制器终止结果，其次回退到最近一步生成观测。"""
        if prepared_state.final_output:
            return prepared_state.final_output

        for observation in reversed(prepared_state.step_observations):
            final_output = observation.output_data.get("final_output")
            if isinstance(final_output, str) and final_output.strip():
                return final_output
        return ""

    @staticmethod
    def _extract_latest_citations(prepared_state: TaskRuntimeState) -> list[dict[str, Any]]:
        """提取最近一步生成观测中的引用列表。"""
        for observation in reversed(prepared_state.step_observations):
            raw_citations = observation.output_data.get("citations")
            if isinstance(raw_citations, list):
                return [dict(item) for item in raw_citations if isinstance(item, dict)]
        return []

    def _build_state_probe(self):
        """构建控制器外部状态探针。

        该探针在控制器每轮迭代前读取最新持久化状态，支持跨请求暂停/取消。
        """

        async def _probe(state: TaskRuntimeState) -> str | None:
            if self.task_runtime_repository is None or not state.task_id:
                return None
            try:
                snapshot = self.task_runtime_repository.get_snapshot(task_id=state.task_id)
            except Exception as error:
                if self._degrade_optional_persistence_if_needed(error=error, operation_name="state_probe"):
                    return None
                raise
            if snapshot is None:
                return None
            return snapshot.record.status

        return _probe

    async def _iterate_controller_stream(
        self,
        state: TaskRuntimeState,
        *,
        state_probe,
    ):
        """兼容控制器新旧签名。

        旧测试替身没有 `state_probe` 参数，这里自动回退到旧调用方式。
        """
        try:
            async for event in self.task_controller.run_stream_from_state(state, state_probe=state_probe):
                yield event
            return
        except TypeError as error:
            if "state_probe" not in str(error):
                raise

        async for event in self.task_controller.run_stream_from_state(state):
            yield event

    def _bootstrap_runtime_state(
        self,
        state: TaskRuntimeState,
        controller_request: TaskControllerRequest,
    ) -> None:
        """为新建任务补齐持久化标识与基础状态。"""
        if not hasattr(state, "task_id"):
            return
        if state.task_id is None:
            state.task_id = f"task_{uuid4().hex}"
        state.status = "pending"
        state.created_at = state.created_at or self._utc_now_iso()
        state.updated_at = self._utc_now_iso()
        state.metadata.setdefault("request_id", controller_request.request_id)
        state.metadata.setdefault("execution_id", controller_request.execution_id)
        state.metadata.setdefault("conversation_id", controller_request.conversation_id)
        state.metadata.setdefault("message_id", controller_request.message_id)
        state.metadata.setdefault("user_id", controller_request.user_id)
        state.metadata.setdefault("original_user_input", controller_request.user_input)

    async def _set_task_status(
        self,
        state: TaskRuntimeState,
        controller_request: TaskControllerRequest,
        *,
        status: str,
        checkpoint_reason: str,
    ) -> None:
        """更新任务状态并持久化。"""
        if self.task_runtime_repository is None or not hasattr(state, "status"):
            return
        state.status = status
        state.updated_at = self._utc_now_iso()
        await self._persist_runtime_progress(
            state,
            controller_request,
            checkpoint_reason=checkpoint_reason,
            force_checkpoint=True,
        )

    async def _persist_runtime_progress(
        self,
        state: TaskRuntimeState,
        controller_request: TaskControllerRequest,
        *,
        checkpoint_reason: str,
        force_checkpoint: bool,
    ) -> None:
        """将当前状态与可选检查点写入持久化仓储。"""
        if self.task_runtime_repository is None or not hasattr(state, "task_id"):
            return
        try:
            self._ensure_state_artifacts(state)
            record = self._build_execution_record(state=state, controller_request=controller_request)
            self.task_runtime_repository.save_execution(
                record=record,
                state=state,
                user_input=controller_request.user_input,
            )
            if not force_checkpoint:
                return
            checkpoint = self._build_checkpoint(state=state, checkpoint_reason=checkpoint_reason)
            state.checkpoint_id = checkpoint.checkpoint_id
            record.checkpoint_id = checkpoint.checkpoint_id
            state.updated_at = self._utc_now_iso()
            self.task_runtime_repository.save_execution(
                record=record,
                state=state,
                user_input=controller_request.user_input,
            )
            self.task_runtime_repository.create_checkpoint(checkpoint=checkpoint, state=state)
        except Exception as error:
            if self._degrade_optional_persistence_if_needed(error=error, operation_name="persist_runtime_progress"):
                return
            raise

    def _require_task_snapshot(self, *, task_id: str, user_id: str) -> TaskRuntimePersistenceSnapshot:
        """读取并校验任务归属。"""
        if self.task_runtime_repository is None:
            raise not_found("当前环境未启用任务运行时持久化")
        try:
            snapshot = self.task_runtime_repository.get_snapshot(task_id=task_id)
        except Exception as error:
            if self._degrade_optional_persistence_if_needed(error=error, operation_name="require_task_snapshot"):
                raise not_found("当前环境未启用任务运行时持久化") from error
            raise
        if snapshot is None or snapshot.record.user_id != user_id:
            raise not_found(
                "任务不存在或无权访问",
                error_code=ErrorCode.SYSTEM_NOT_FOUND,
                error="TaskRuntimeNotFound",
            )
        return snapshot

    async def _apply_lifecycle_action(
        self,
        *,
        snapshot: TaskRuntimePersistenceSnapshot,
        action: TaskLifecycleAction,
        reason: str | None,
        metadata: dict[str, Any] | None,
        next_status: str,
    ) -> None:
        """应用生命周期动作并持久化新的状态与检查点。

        这是 pause / resume / cancel / retry 共用的统一处理入口。
        通过集中实现，可以保证：
        - 状态更新规则一致；
        - 干预记录格式一致；
        - 检查点原因命名一致；
        - 后续审计与排障更容易。
        """
        snapshot.state.status = next_status
        snapshot.state.updated_at = self._utc_now_iso()
        snapshot.record.status = next_status
        snapshot.record.updated_at = snapshot.state.updated_at
        snapshot.state.metadata.setdefault("interventions", [])
        interventions = list(snapshot.state.metadata.get("interventions") or [])
        interventions.append(
            {
                "action": action,
                "reason": reason or "",
                "metadata": dict(metadata or {}),
                "created_at": self._utc_now_iso(),
            }
        )
        snapshot.state.metadata["interventions"] = interventions
        controller_request = self._build_controller_request_from_snapshot(snapshot)
        checkpoint_reason = f"action:{action}"
        if reason:
            checkpoint_reason = f"{checkpoint_reason}:{reason}"
        await self._persist_runtime_progress(
            snapshot.state,
            controller_request,
            checkpoint_reason=checkpoint_reason,
            force_checkpoint=True,
        )
        # 若未配置任务运行时仓储，说明当前环境不支持任务中心增强能力，直接跳过落库。
        if self.task_runtime_repository is None:
            return
        refreshed_snapshot = self.task_runtime_repository.get_snapshot(task_id=snapshot.record.task_id)
        if refreshed_snapshot is not None:
            snapshot.record = refreshed_snapshot.record
            snapshot.state = refreshed_snapshot.state
            snapshot.latest_checkpoint = refreshed_snapshot.latest_checkpoint

    def _degrade_optional_persistence_if_needed(self, *, error: Exception, operation_name: str) -> bool:
        """识别可降级的持久化异常并关闭后续 task-runtime 落库。

        当前问题场景是运行时表尚未创建；此时聊天主链路仍应继续执行，
        仅禁用任务中心相关的持久化增强能力。
        """
        # 只有识别为“任务运行时表缺失”这类可预期基础设施问题时，才允许自动降级。
        if not self._is_missing_task_runtime_table_error(error):
            return False
        if not self._task_runtime_persistence_degraded:
            self.logger.warning(
                "任务运行时持久化表不可用，已自动降级并跳过后续 `%s` 落库：%s",
                operation_name,
                error,
                exc_info=True,
            )
        self._task_runtime_persistence_degraded = True
        self.task_runtime_repository = None
        return True

    @staticmethod
    def _is_missing_task_runtime_table_error(error: Exception) -> bool:
        """判断异常是否为 task-runtime 相关表缺失。

        这里兼容常见数据库错误文本，避免直接绑定某个数据库驱动类型。
        """
        existence_markers = (
            "doesn't exist",
            "does not exist",
            "unknown table",
            "no such table",
        )
        table_markers = (
            "task_runtime_executions",
            "task_runtime_checkpoints",
            "task_runtime_artifacts",
        )

        current_error: Exception | None = error
        visited_error_ids: set[int] = set()
        # 沿着异常链逐层向下查找，兼容原始异常被多层包装的情况。
        while current_error is not None and id(current_error) not in visited_error_ids:
            visited_error_ids.add(id(current_error))
            error_message = str(current_error).lower()
            has_task_runtime_table = any(table_marker in error_message for table_marker in table_markers)
            has_missing_table_marker = any(marker in error_message for marker in existence_markers)
            has_postgres_missing_relation = "relation" in error_message and "does not exist" in error_message
            has_known_database_code = "1146" in error_message or "42p01" in error_message
            if has_task_runtime_table and (
                has_missing_table_marker or has_postgres_missing_relation or has_known_database_code
            ):
                return True
            current_error = current_error.__cause__ or current_error.__context__
        return False

    @staticmethod
    def _clear_terminal_state(state: TaskRuntimeState) -> None:
        """清理终止态，便于任务恢复或重试。

        这里会把 `terminated`、`termination`、`final_output` 等终止态字段复位，
        让任务重新回到可推进状态，但不会清空整个业务上下文。
        """
        state.terminated = False
        state.termination = None
        state.final_output = None
        state.status = "pending"
        state.updated_at = TaskRuntimeApplicationService._utc_now_iso()

    def _build_execution_record(
        self,
        *,
        state: TaskRuntimeState,
        controller_request: TaskControllerRequest,
    ) -> TaskExecutionRecord:
        """从当前控制器状态构建执行摘要。

        执行摘要主要面向列表、概览和轻量查询场景，
        不要求保存全部细节，但要覆盖最关键的链路字段和当前位置。
        """
        return TaskExecutionRecord(
            task_id=state.task_id or f"task_{uuid4().hex}",
            request_id=controller_request.request_id or "",
            execution_id=controller_request.execution_id or "",
            user_id=controller_request.user_id,
            conversation_id=controller_request.conversation_id,
            message_id=controller_request.message_id,
            status=state.status,
            current_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
            current_step_id=state.current_step_id,
            checkpoint_id=state.checkpoint_id,
            created_at=state.created_at,
            updated_at=state.updated_at,
            metadata=dict(state.metadata),
        )

    def _build_checkpoint(self, *, state: TaskRuntimeState, checkpoint_reason: str) -> TaskCheckpoint:
        """从运行时状态构建标准检查点。

        检查点是任务恢复与排障的关键结构，因此会记录：
        - 当前状态；
        - 已完成步骤；
        - 当前计划与步骤位置；
        - 本次生成检查点的原因。
        """
        return TaskCheckpoint(
            task_id=state.task_id,
            execution_id=str((state.metadata or {}).get("execution_id") or ""),
            status=state.status,
            iteration_count=state.iteration_count,
            completed_step_ids=list(state.completed_step_ids),
            latest_plan_id=state.current_plan.plan_id if state.current_plan is not None else None,
            latest_step_id=state.current_step_id,
            checkpoint_reason=checkpoint_reason,
            metadata={
                "goal_id": state.goal.goal_id,
                "terminated": state.terminated,
            },
        )

    def _ensure_state_artifacts(self, state: TaskRuntimeState) -> None:
        """补齐基础标准产物，避免复杂任务过程结果全部散落在自由文本中。

        该方法会把 plan / final_output / evaluation_report 等关键结果收敛为标准产物，
        这样前端、任务中心、审计逻辑都可以基于统一结构消费，而不是各自解析文本。
        """
        # 复制一份当前产物列表，避免直接在原列表上边遍历边修改。
        artifacts = list(state.artifacts)
        existing_plan_ids = {artifact.source_plan_id for artifact in artifacts if artifact.artifact_type == "plan"}
        if state.current_plan is not None and state.current_plan.plan_id not in existing_plan_ids:
            artifacts.append(
                TaskArtifact(
                    artifact_type="plan",
                    title="当前任务计划",
                    content=state.current_plan.model_dump(),
                    source_plan_id=state.current_plan.plan_id,
                    metadata={"version": state.current_plan.version},
                )
            )

        if state.final_output and not any(artifact.metadata.get("kind") == "final_output" for artifact in artifacts):
            artifacts.append(
                TaskArtifact(
                    artifact_type="text",
                    title="最终输出",
                    content={"final_output": state.final_output},
                    metadata={"kind": "final_output"},
                )
            )

        if state.evaluation_report is not None and not any(
            artifact.metadata.get("kind") == "evaluation_report" for artifact in artifacts
        ):
            artifacts.append(
                TaskArtifact(
                    artifact_type="report",
                    title="任务评估报告",
                    content=state.evaluation_report.model_dump(),
                    metadata={"kind": "evaluation_report"},
                )
            )
        state.artifacts = artifacts

    def _build_controller_request_from_snapshot(
        self,
        snapshot: TaskRuntimePersistenceSnapshot,
    ) -> TaskControllerRequest:
        """从持久化快照恢复控制器请求。

        当任务从数据库恢复时，控制器原始请求对象通常已经不存在，
        需要根据记录与状态中的链路字段重建出等价请求。
        """
        metadata = dict(snapshot.state.metadata or {})
        metadata.setdefault("task_id", snapshot.record.task_id)
        return TaskControllerRequest(
            user_id=snapshot.record.user_id,
            conversation_id=snapshot.record.conversation_id,
            user_input=str(metadata.get("original_user_input") or snapshot.state.goal.original_user_input),
            message_id=snapshot.record.message_id,
            request_id=snapshot.record.request_id,
            execution_id=snapshot.record.execution_id,
            metadata=metadata,
        )

    @staticmethod
    def _utc_now_iso() -> str:
        """统一生成 UTC ISO 时间文本。

        使用 UTC 并以 `Z` 结尾，便于前后端、日志、持久化层统一解析。
        """
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _build_controller_request(
        *,
        user_id: str,
        conversation_id: str,
        user_input: str,
        message_id: str | None,
        request_id: str | None,
        metadata: dict[str, Any] | None,
    ) -> TaskControllerRequest:
        """统一生成控制器请求，确保链路字段齐全。

        该方法负责生成或补齐 request_id、message_id、execution_id 等链路字段，
        保证后续日志、SSE、持久化记录都能通过统一标识串联起来。
        """
        # 若上游未提供链路标识，则在应用层统一生成，避免后续链路字段缺失。
        resolved_request_id = request_id or f"req_{uuid4().hex}"
        resolved_message_id = message_id or f"msg_{uuid4().hex}"
        execution_id = f"exec_{uuid4().hex}"
        request_metadata = dict(metadata or {})
        request_metadata.setdefault("request_id", resolved_request_id)
        request_metadata.setdefault("message_id", resolved_message_id)
        request_metadata.setdefault("conversation_id", conversation_id)
        request_metadata.setdefault("execution_id", execution_id)
        return TaskControllerRequest(
            user_id=user_id,
            conversation_id=conversation_id,
            user_input=user_input,
            message_id=resolved_message_id,
            request_id=resolved_request_id,
            execution_id=execution_id,
            metadata=request_metadata,
        )

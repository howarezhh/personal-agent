# -*- coding: utf-8 -*-
from __future__ import annotations

"""
"""

import time
import uuid
from typing import AsyncGenerator, Optional, Dict, Any, List
from datetime import datetime


from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput
from backend.agents.base.stream_chunk import StreamChunk
from backend.file_processors.document_registry import list_agent_supported_format_names
from backend.file_processors import BaseParser, DocumentChunker, ParsedContent, get_parser_registry
from backend.models.file import File, FileUpdate, ProcessingStatus, FileType, FileChunk
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate
from backend.domain.knowledge import build_chunk_vector_metadata, delete_file_knowledge_data
from backend.utils.embedding_client import get_embedding_client
from backend.utils.vector_db_client import get_vector_db_client


class FileProcessorAgent(BaseAgent):
    """
    """
    def __init__(self):
        """
        
        """
        super().__init__(
            agent_name="file_processor_agent",
            agent_type="file_processor"
        )

        self.parser_registry = get_parser_registry()
        self.parsers: Dict[str, BaseParser] = self.parser_registry.all()

        chunk_size = self._get_config_value("chunk_size", 1000)  # 与配置文件保持一致
        chunk_overlap = self._get_config_value("chunk_overlap", 100)
        # 分块策略需要和嵌入模型的最大输入限制对齐，避免后续向量化时单块过长。
        embedding_config = self.config_manager.get_model_config("embedding")
        embedding_max_input_tokens = int(embedding_config.get("max_input_tokens", 512) or 512)
        embedding_reserved_tokens = int(embedding_config.get("reserved_tokens", 32) or 32)
        chunk_token_limit = max(1, embedding_max_input_tokens - max(0, embedding_reserved_tokens))
        # 优先使用 embedding 模型自己的 tokenizer 做精确控长；若初始化失败则回退到启发式估算。
        token_counter = None
        try:
            token_counter = get_embedding_client().count_tokens
        except Exception as error:
            self.logger.warning("初始化精确 token 计数器失败，将回退到启发式控长: %s", error)

        self.chunker = DocumentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_chunk_tokens=chunk_token_limit,
            token_counter=token_counter,
        )

        self.file_repo = get_file_repository()
        self.chunk_repo = get_file_chunk_repository()
        self.execution_repo = get_agent_execution_repository()

        try:
            # 尝试连接向量库；如不可用，则仅跳过向量化阶段，不阻塞主流程。
            self.vector_store = get_vector_db_client()
            self.vector_enabled = True
            self.logger.info("File processor agent initialized")
        except Exception as e:
            self.logger.warning("向量数据库客户端不可用: %s", str(e))
            self.vector_store = None
            self.vector_enabled = False

        # 支持格式展示同样收敛到统一注册表，避免配置文档与实际能力再次漂移。
        self.supported_formats = list_agent_supported_format_names()
        self.max_file_size = self._get_config_value("max_file_size", 50)  # MB

        self.logger.info("最大文件大小: %sMB", self.max_file_size)

    def _get_parser_for_file(self, file_type: FileType) -> Optional[BaseParser]:
        """
        
            file_type: 当前待处理文件的类型枚举。
        
        """
        return self.parser_registry.get_for_file_type(file_type)

    def _update_processing_progress(
        self,
        file: File,
        *,
        stage: str,
        progress: int,
        status: ProcessingStatus = ProcessingStatus.PROCESSING,
        error_message: str | None = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        
            progress: 当前阶段对应的进度百分比。
            extra_metadata: 需要额外合并写回的元数据。
        
        """
        metadata = {
            **(file.metadata or {}),
            "processing_stage": stage,
            "processing_progress": progress,
            # 同步回写任务状态，避免 `metadata.task_status` 长时间停留在初始值。
            "task_status": status.value if hasattr(status, "value") else str(status),
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        self.file_repo.update_file(
            file.file_id,
            FileUpdate(
                processing_status=status,
                error_message=error_message,
                metadata=metadata,
            )
        )
        file.metadata = metadata
        file.processing_status = status
        if error_message is not None:
            file.error_message = error_message

    @staticmethod
    def _build_chunking_metadata(file_id: str, file: File) -> Dict[str, Any]:
        """统一构造切块阶段的基础元数据，避免同一语义在多处手写漂移。"""
        return {
            "file_id": file_id,
            "filename": file.original_filename,
            "file_type": file.file_type,
            "file_extension": f".{getattr(file, 'original_filename', '').rsplit('.', 1)[-1].lower()}"
            if "." in getattr(file, "original_filename", "")
            else "",
        }

    @staticmethod
    def _build_file_chunks(file_id: str, chunks: List[FileChunk]) -> List[FileChunk]:
        """把切块结果标准化为可持久化的 FileChunk 列表。"""
        file_chunks: List[FileChunk] = []
        for index, chunk in enumerate(chunks):
            file_chunks.append(
                FileChunk(
                    chunk_id=getattr(chunk, "chunk_id", None) or str(uuid.uuid4()),
                    file_id=file_id,
                    chunk_index=index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    start_char=getattr(chunk, "start_char", None),
                    end_char=getattr(chunk, "end_char", None),
                    token_count=getattr(chunk, "token_count", None),
                    metadata=chunk.metadata,
                )
            )
        return file_chunks

    @staticmethod
    def _is_empty_parsed_content(parsed_content: ParsedContent) -> bool:
        """统一判断解析结果是否为空，避免批处理与流式分支逻辑漂移。"""
        parsed_text = str(getattr(parsed_content, "text", "") or "").strip()
        has_structured_payload = bool(
            parsed_text
            or getattr(parsed_content, "pages", None)
            or getattr(parsed_content, "tables", None)
            or getattr(parsed_content, "blocks", None)
        )
        return (not has_structured_payload) or bool((parsed_content.metadata or {}).get("empty_content"))

    @staticmethod
    def _build_empty_parse_error(parsed_content: ParsedContent) -> str:
        """统一构造空文档错误消息，并尽量保留 OCR 提示。"""
        ocr_hint = (parsed_content.metadata or {}).get("ocr_skipped_reason")
        error_msg = "文档解析结果为空，无法建立知识索引"
        if ocr_hint:
            error_msg = f"{error_msg}；{ocr_hint}"
        return error_msg

    def _cleanup_existing_knowledge_data(self, *, file_id: str) -> Dict[str, Any]:
        """重建前先清理旧数据；若旧向量删不掉，则直接中止，避免新旧数据混合。"""
        return delete_file_knowledge_data(
            file_id=file_id,
            chunk_repo=self.chunk_repo,
            vector_store=self.vector_store if self.vector_enabled else None,
            log=self.logger,
        )

    def _vectorize_file_chunks(self, *, file: File, file_chunks: List[FileChunk]) -> Dict[str, Any]:
        """统一封装向量化结果，显式返回成功/失败与缺失统计。"""
        total_chunks = len(file_chunks)
        if not self.vector_enabled or not file_chunks:
            return {
                "success": True,
                "vectorized_chunk_ids": [],
                "vectorized_chunk_count": 0,
                "missing_vector_chunk_count": 0,
                "vectorization_status": None,
                "can_retry_vectorization": False,
                "error_message": None,
            }

        try:
            documents = [chunk.content for chunk in file_chunks]
            metadatas = [build_chunk_vector_metadata(file, chunk) for chunk in file_chunks]
            ids = [chunk.chunk_id for chunk in file_chunks]
            embedding_client = get_embedding_client()
            embeddings = embedding_client.embed_texts(documents)

            valid_data = [
                (doc, emb, meta, chunk_id)
                for doc, emb, meta, chunk_id in zip(documents, embeddings, metadatas, ids)
                if emb is not None
            ]
            if not valid_data:
                return {
                    "success": False,
                    "vectorized_chunk_ids": [],
                    "vectorized_chunk_count": 0,
                    "missing_vector_chunk_count": total_chunks,
                    "vectorization_status": "failed",
                    "can_retry_vectorization": True,
                    "error_message": "所有文本块的向量生成都失败了",
                }

            valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)
            success = self.vector_store.add_documents(
                documents=list(valid_documents),
                embeddings=list(valid_embeddings),
                metadatas=list(valid_metadatas),
                ids=list(valid_ids),
            )
            if not success:
                return {
                    "success": False,
                    "vectorized_chunk_ids": [],
                    "vectorized_chunk_count": 0,
                    "missing_vector_chunk_count": total_chunks,
                    "vectorization_status": "failed",
                    "can_retry_vectorization": True,
                    "error_message": self.vector_store.last_error or "向量库写入失败",
                }

            vectorized_chunk_ids = list(valid_ids)
            for chunk in file_chunks:
                if chunk.chunk_id in vectorized_chunk_ids:
                    self.chunk_repo.update_chunk_vector_id(chunk.chunk_id, chunk.chunk_id)

            missing_vector_chunk_count = max(0, total_chunks - len(vectorized_chunk_ids))
            if missing_vector_chunk_count:
                return {
                    "success": False,
                    "vectorized_chunk_ids": vectorized_chunk_ids,
                    "vectorized_chunk_count": len(vectorized_chunk_ids),
                    "missing_vector_chunk_count": missing_vector_chunk_count,
                    "vectorization_status": "failed",
                    "can_retry_vectorization": True,
                    "error_message": f"仅有 {len(vectorized_chunk_ids)}/{total_chunks} 个文本块完成向量化",
                }

            return {
                "success": True,
                "vectorized_chunk_ids": vectorized_chunk_ids,
                "vectorized_chunk_count": len(vectorized_chunk_ids),
                "missing_vector_chunk_count": 0,
                "vectorization_status": "succeeded",
                "can_retry_vectorization": False,
                "error_message": None,
            }
        except Exception as error:
            self.logger.error("Error during vectorization: %s", str(error), exc_info=True)
            return {
                "success": False,
                "vectorized_chunk_ids": [],
                "vectorized_chunk_count": 0,
                "missing_vector_chunk_count": total_chunks,
                "vectorization_status": "failed",
                "can_retry_vectorization": True,
                "error_message": str(error),
            }

    async def process_file(self, file_id: str) -> Dict[str, Any]:
        """
        
            file_id: 待处理文件的唯一标识。
        
        """
        try:
            # 先读取文件记录，后续的解析、分块、向量化都基于该文件实体展开。
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                return {
                    "success": False,
                    "error": f"文件不存在: {file_id}"
                }

            self.logger.info(f"Processing file: {file.original_filename} ({file.file_type})")

            # 任务启动后立即写回初始进度，便于前端或任务系统及时感知状态变化。
            self._update_processing_progress(file, stage="queued", progress=5)

            parser = self._get_parser_for_file(file.file_type)
            if not parser:
                error_msg = self._get_error_message(
                    "unsupported_format",
                    file_format=file.file_type,
                    supported_formats=", ".join(self.supported_formats)
                )
                self._update_processing_progress(
                    file,
                    stage="failed",
                    progress=100,
                    status=ProcessingStatus.FAILED,
                    error_message=error_msg,
                )
                return {
                    "success": False,
                    "error": error_msg
                }

            self._update_processing_progress(file, stage="parsing", progress=20)
            self.logger.info(f"Parsing file with {parser.__class__.__name__}")
            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "Document parsing failed")
                self._update_processing_progress(
                    file,
                    stage="failed",
                    progress=100,
                    status=ProcessingStatus.FAILED,
                    error_message=error_msg,
                )
                return {
                    "success": False,
                    "error": error_msg
                }

            parsed_content = parse_result["content"]
            if self._is_empty_parsed_content(parsed_content):
                error_msg = self._build_empty_parse_error(parsed_content)
                self._update_processing_progress(
                    file,
                    stage="failed",
                    progress=100,
                    status=ProcessingStatus.FAILED,
                    error_message=error_msg,
                    extra_metadata={
                        **(parsed_content.metadata or {}),
                        "chunk_count": 0,
                    },
                )
                return {"success": False, "error": error_msg}

            self._update_processing_progress(file, stage="chunking", progress=45)
            self.logger.info("Chunking document")
            # 将解析结果切分为适合检索和向量化的文本块，并控制块大小与重叠范围。
            chunks = self.chunker.chunk_parsed_content(
                parsed_content=parsed_content,
                metadata=self._build_chunking_metadata(file_id, file),
            )

            self.logger.info(f"Created {len(chunks)} chunks")
            if not chunks:
                error_msg = "文档切块结果为空，无法建立知识索引"
                self._update_processing_progress(
                    file,
                    stage="failed",
                    progress=100,
                    status=ProcessingStatus.FAILED,
                    error_message=error_msg,
                    extra_metadata={
                        **(parsed_content.metadata or {}),
                        "chunk_count": 0,
                    },
                )
                return {"success": False, "error": error_msg}

            self._update_processing_progress(file, stage="saving_chunks", progress=65)
            self.logger.info("Saving chunks to database")
            file_chunks = self._build_file_chunks(file_id, chunks)

            cleanup_result = self._cleanup_existing_knowledge_data(file_id=file_id)
            if cleanup_result.get("vector_delete_attempted") and not cleanup_result.get("vector_delete_success", True):
                error_msg = "旧向量删除失败，已中止本次重建以避免新旧索引混合"
                self._update_processing_progress(
                    file,
                    stage="failed",
                    progress=100,
                    status=ProcessingStatus.FAILED,
                    error_message=error_msg,
                    extra_metadata={
                        **(parsed_content.metadata or {}),
                        "chunk_count": len(chunks),
                        "vectorization_status": "failed",
                        "can_retry_vectorization": True,
                    },
                )
                return {"success": False, "error": error_msg}
            if cleanup_result["chunk_count"] or cleanup_result["vector_count"]:
                self.logger.info(
                    f"Removed stale knowledge data before reprocessing: file_id={file_id}, "
                    f"chunks={cleanup_result['chunk_count']}, vectors={cleanup_result['vector_count']}"
                )

            if file_chunks:
                # 批量保存文本块，为后续检索、引用和向量化提供稳定数据基础。
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            # 仅当向量库可用且存在文本块时，才进入向量化阶段。
            if self.vector_enabled and file_chunks:
                self._update_processing_progress(file, stage="vectorizing", progress=80)
                self.logger.info("开始向量化文本块")
                vectorization_result = self._vectorize_file_chunks(file=file, file_chunks=file_chunks)
                if not vectorization_result["success"]:
                    error_msg = vectorization_result["error_message"] or "文档向量化失败"
                    self._update_processing_progress(
                        file,
                        stage="failed",
                        progress=100,
                        status=ProcessingStatus.FAILED,
                        error_message=error_msg,
                        extra_metadata={
                            **(parsed_content.metadata or {}),
                            "chunk_count": len(chunks),
                            "vectorization_status": vectorization_result["vectorization_status"],
                            "vectorized_chunk_count": vectorization_result["vectorized_chunk_count"],
                            "missing_vector_chunk_count": vectorization_result["missing_vector_chunk_count"],
                            "can_retry_vectorization": vectorization_result["can_retry_vectorization"],
                        },
                    )
                    return {"success": False, "error": error_msg}
            else:
                vectorization_result = {
                    "vectorization_status": None,
                    "vectorized_chunk_count": 0,
                    "missing_vector_chunk_count": 0,
                    "can_retry_vectorization": False,
                }

            self._update_processing_progress(file, stage="summarizing", progress=90)
            summary = await self._generate_summary(
                parsed_content,
                chunks,
                file.original_filename,
                file.file_type
            )

            self.file_repo.update_file(
                file_id,
                FileUpdate(
                    processing_status=ProcessingStatus.COMPLETED,
                    processed_at=datetime.utcnow(),
                    chunk_count=len(chunks),
                    summary=summary,
                    metadata={
                        **(file.metadata or {}),
                        **parsed_content.metadata,
                        "chunk_count": len(chunks),
                        "vectorization_status": vectorization_result.get("vectorization_status"),
                        "vectorized_chunk_count": vectorization_result.get("vectorized_chunk_count", 0),
                        "missing_vector_chunk_count": vectorization_result.get("missing_vector_chunk_count", 0),
                        "can_retry_vectorization": vectorization_result.get("can_retry_vectorization", False),
                        "processing_stage": "completed",
                        "processing_progress": 100,
                        "task_status": ProcessingStatus.COMPLETED.value,
                    }
                )
            )

            self.logger.info(f"File processing completed: {file.original_filename}")

            return {
                "success": True,
                "file_id": file_id,
                "chunk_count": len(chunks),
                "summary": summary,
                "metadata": parsed_content.metadata
            }

        except Exception as e:
            self.logger.error(f"Error processing file {file_id}: {str(e)}", exc_info=True)

            try:
                if file:
                    self._update_processing_progress(
                        file,
                        stage="failed",
                        progress=100,
                        status=ProcessingStatus.FAILED,
                        error_message=str(e),
                    )
            except Exception as update_error:
                self.logger.error(f"Failed to update file status: {str(update_error)}")

            return {
                "success": False,
                "error": str(e)
            }

    async def _generate_summary(self, parsed_content, chunks: List, filename: str, file_type: str) -> str:
        """
        生成文档摘要。

        Args:
            parsed_content: 解析后的文档内容对象。
            chunks: 文档切分后的文本块列表。
            filename: 原始文件名。
            file_type: 文件类型字符串。
        """
        try:
            metadata = parsed_content.metadata
            total_pages = metadata.get("total_pages", 0)

            text = parsed_content.text
            content_preview = text[:1000] if len(text) > 1000 else text

            prompt_template, prompt_variables = self.prompt_manager.build_chat_prompt_call(
                user_prompt_key="file_processor.summary_generation_prompt",
                system_prompt_key="file_processor.file_processor_system_prompt",
                user_variables={
                    "filename": filename,
                    "file_type": file_type,
                    "total_pages": total_pages,
                    "chunk_count": len(chunks),
                    "content_preview": content_preview,
                },
            )

            summary = await self.model_manager.invoke_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=0.5,
                max_tokens=300,
            )

            stats = self._build_stats_summary(metadata, len(chunks))
            if stats:
                summary = f"[{stats}] {summary}"

            return summary

        except Exception as e:
            self.logger.error(f"Failed to generate LLM summary: {str(e)}")
            return self._generate_simple_summary(parsed_content, chunks)

    def _generate_simple_summary(self, parsed_content, chunks: List) -> str:
        """
        生成不依赖 LLM 的简要摘要。

        Args:
            parsed_content: 解析后的文档内容对象。
            chunks: 文档切分后的文本块列表。
        """
        text = parsed_content.text
        if len(text) > 200:
            summary = text[:200] + "..."
        else:
            summary = text

        metadata = parsed_content.metadata
        stats = self._build_stats_summary(metadata, len(chunks))
        if stats:
            summary = f"[{stats}] {summary}"

        return summary

    def _build_stats_summary(self, metadata: dict, chunk_count: int) -> str:
        """
        构建文档统计摘要文本。

        Args:
            metadata: 解析结果中的统计元数据。
            chunk_count: 当前文件的文本块数量。
        """
        stats = []

        if "total_pages" in metadata:
            stats.append(f"{metadata['total_pages']} 页")

        if "paragraph_count" in metadata:
            stats.append(f"{metadata['paragraph_count']} 段")

        if "table_count" in metadata:
            stats.append(f"{metadata['table_count']} 个表格")

        stats.append(f"{chunk_count} 个文本块")

        return ', '.join(stats) if stats else ""

    def _get_error_message(self, error_type: str, **kwargs) -> str:
        """
        根据错误类型生成统一错误文案。

        Args:
            error_type: 错误类型标识。
            kwargs: 生成错误文案时需要补充的动态参数。
        """
        error_prompt_prefix = "file_processor.error_handling"
        error_prompt_key = f"{error_prompt_prefix}.{error_type}"
        if self.prompt_manager.get_prompt(error_prompt_key):
            return self.prompt_manager.render_prompt(error_prompt_key, **kwargs)
        return self.prompt_manager.render_prompt(
            f"{error_prompt_prefix}.unknown_error",
            error_message=kwargs.get("error_message", "unknown error"),
        )

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        执行非流式文档处理，并将结果封装为统一的 `AgentOutput`。
        """
        start_time = time.time()

        try:
            file_id = getattr(agent_input, "file_id", None) or agent_input.content

            result = await self.process_file(file_id)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 持久化本次 Agent 执行记录，便于审计、回溯与排障。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"file_id": file_id},
                output_data=result,
                status="success" if result["success"] else "failed",
                execution_time_ms=execution_time_ms
            )
            self.execution_repo.create_execution(execution_create)

            if result["success"]:
                return self._create_output(
                    status="success",
                    execution_time_ms=execution_time_ms,
                    file_id=file_id,
                    chunk_count=result["chunk_count"],
                    summary=result.get("summary"),
                    metadata=result.get("metadata")
                )
            else:
                return self._create_output(
                    content="",
                    status="failed",
                    error_message=result["error"],
                    execution_time_ms=execution_time_ms
                )

        except Exception as e:
            self.logger.error(f"Error in execute: {str(e)}", exc_info=True)
            execution_time_ms = int((time.time() - start_time) * 1000)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """
        
        
        """
        try:
            file_id = getattr(agent_input, "file_id", None) or agent_input.content

            yield StreamChunk.create_thinking("Starting document processing...")

            # 先读取文件记录，后续解析、分块和向量化都基于该文件实体展开。
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                yield StreamChunk.create_error(f"文件不存在: {file_id}")
                return

            yield StreamChunk.create_thinking(f"Parsing document: {file.original_filename}")

            self.file_repo.update_file(
                file_id,
                FileUpdate(processing_status=ProcessingStatus.PROCESSING)
            )

            parser = self._get_parser_for_file(file.file_type)
            if not parser:
                error_msg = self._get_error_message(
                    "unsupported_format",
                    file_format=file.file_type,
                    supported_formats=", ".join(self.supported_formats)
                )
                self.file_repo.update_file(
                    file_id,
                    FileUpdate(
                        processing_status=ProcessingStatus.FAILED,
                        error_message=error_msg
                    )
                )
                yield StreamChunk.create_error(error_msg)
                return

            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "Document parsing failed")
                self.file_repo.update_file(
                    file_id,
                    FileUpdate(
                        processing_status=ProcessingStatus.FAILED,
                        error_message=error_msg
                    )
                )
                yield StreamChunk.create_error(error_msg)
                return

            parsed_content = parse_result["content"]
            if self._is_empty_parsed_content(parsed_content):
                error_msg = self._build_empty_parse_error(parsed_content)
                self.file_repo.update_file(
                    file_id,
                    FileUpdate(
                        processing_status=ProcessingStatus.FAILED,
                        error_message=error_msg,
                    )
                )
                yield StreamChunk.create_error(error_msg)
                return

            yield StreamChunk.create_thinking("Splitting document into chunks...")

            # 将解析结果切分为适合检索和向量化的文本块，并控制块大小与重叠范围。
            chunks = self.chunker.chunk_parsed_content(
                parsed_content=parsed_content,
                metadata=self._build_chunking_metadata(file_id, file),
            )

            yield StreamChunk.create_thinking(f"Generated {len(chunks)} chunks")
            if not chunks:
                error_msg = "文档切块结果为空，无法建立知识索引"
                self.file_repo.update_file(
                    file_id,
                    FileUpdate(
                        processing_status=ProcessingStatus.FAILED,
                        error_message=error_msg,
                        metadata={
                            **(file.metadata or {}),
                            **(parsed_content.metadata or {}),
                            "chunk_count": 0,
                        },
                    ),
                )
                yield StreamChunk.create_error(error_msg)
                return

            yield StreamChunk.create_thinking("Saving text chunks...")
            file_chunks = self._build_file_chunks(file_id, chunks)

            cleanup_result = self._cleanup_existing_knowledge_data(file_id=file_id)
            if cleanup_result.get("vector_delete_attempted") and not cleanup_result.get("vector_delete_success", True):
                error_msg = "旧向量删除失败，已中止本次重建以避免新旧索引混合"
                self.file_repo.update_file(
                    file_id,
                    FileUpdate(
                        processing_status=ProcessingStatus.FAILED,
                        error_message=error_msg,
                        metadata={
                            **(file.metadata or {}),
                            **(parsed_content.metadata or {}),
                            "chunk_count": len(chunks),
                            "vectorization_status": "failed",
                            "can_retry_vectorization": True,
                        },
                    ),
                )
                yield StreamChunk.create_error(error_msg)
                return
            if cleanup_result["chunk_count"] or cleanup_result["vector_count"]:
                self.logger.info(
                    f"Removed stale knowledge data before reprocessing: file_id={file_id}, "
                    f"chunks={cleanup_result['chunk_count']}, vectors={cleanup_result['vector_count']}"
                )

            if file_chunks:
                # 批量保存文本块，为后续检索、引用和向量化提供稳定数据基础。
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            # 仅当向量库可用且存在文本块时，才进入向量化阶段。
            if self.vector_enabled and file_chunks:
                yield StreamChunk.create_thinking("Vectorizing document chunks...")
                vectorization_result = self._vectorize_file_chunks(file=file, file_chunks=file_chunks)
                if not vectorization_result["success"]:
                    error_msg = vectorization_result["error_message"] or "文档向量化失败"
                    self.file_repo.update_file(
                        file_id,
                        FileUpdate(
                            processing_status=ProcessingStatus.FAILED,
                            error_message=error_msg,
                            metadata={
                                **(file.metadata or {}),
                                **(parsed_content.metadata or {}),
                                "chunk_count": len(chunks),
                                "vectorization_status": vectorization_result["vectorization_status"],
                                "vectorized_chunk_count": vectorization_result["vectorized_chunk_count"],
                                "missing_vector_chunk_count": vectorization_result["missing_vector_chunk_count"],
                                "can_retry_vectorization": vectorization_result["can_retry_vectorization"],
                            },
                        ),
                    )
                    yield StreamChunk.create_error(error_msg)
                    return
                yield StreamChunk.create_thinking(f"Vectorized {vectorization_result['vectorized_chunk_count']} chunks")
            else:
                vectorization_result = {
                    "vectorization_status": None,
                    "vectorized_chunk_count": 0,
                    "missing_vector_chunk_count": 0,
                    "can_retry_vectorization": False,
                }

            yield StreamChunk.create_thinking("Generating document summary...")
            summary = await self._generate_summary(
                parsed_content,
                chunks,
                file.original_filename,
                file.file_type
            )

            self.file_repo.update_file(
                file_id,
                FileUpdate(
                    processing_status=ProcessingStatus.COMPLETED,
                    processed_at=datetime.utcnow(),
                    chunk_count=len(chunks),
                    summary=summary,
                    metadata={
                        **(file.metadata or {}),
                        **parsed_content.metadata,
                        "chunk_count": len(chunks),
                        "vectorization_status": vectorization_result.get("vectorization_status"),
                        "vectorized_chunk_count": vectorization_result.get("vectorized_chunk_count", 0),
                        "missing_vector_chunk_count": vectorization_result.get("missing_vector_chunk_count", 0),
                        "can_retry_vectorization": vectorization_result.get("can_retry_vectorization", False),
                        "task_status": ProcessingStatus.COMPLETED.value,
                    }
                )
            )

            # `result_message`：流式输出给前端的最终摘要文本，需在使用前显式初始化。
            result_message = ""
            result_message += f"文件名: {file.original_filename}\n"
            result_message += f"文本块数: {len(chunks)}\n"
            result_message += f"摘要: {summary}\n"

            yield StreamChunk.create_content(result_message)

            # 持久化本次 Agent 执行记录，便于审计、回溯与排障。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"file_id": file_id},
                output_data={
                    "success": True,
                    "file_id": file_id,
                    "chunk_count": len(chunks),
                    "summary": summary
                },
                status="success"
            )
            self.execution_repo.create_execution(execution_create)

        except Exception as e:
            self.logger.error(f"Error in execute_stream: {str(e)}", exc_info=True)

    async def process_multiple_files(self, file_ids: List[str]) -> Dict[str, Any]:
        """
        批量处理多个文件。

        Args:
            file_ids: 待批量处理的文件 ID 列表。
        """
        results = []

        for file_id in file_ids:
            result = await self.process_file(file_id)
            results.append({
                "file_id": file_id,
                **result
            })

        success_count = sum(1 for r in results if r["success"])
        failed_count = len(results) - success_count

        return {
            "total": len(file_ids),
            "success": success_count,
            "failed": failed_count,
            "results": results
        }



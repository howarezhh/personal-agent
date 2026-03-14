"""
文件处理智能体
负责文件处理的完整流程
"""

import os
import time
import uuid
from typing import AsyncGenerator, Optional, Dict, Any, List
from datetime import datetime

from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput, ExecutionStatus
from backend.agents.base.stream_chunk import StreamChunk
from backend.file_processors.parsers.base_parser import BaseParser
from backend.file_processors.parsers.parser_registry import get_parser_registry
from backend.file_processors.chunker import DocumentChunker
from backend.models.file import File, FileUpdate, ProcessingStatus, FileType, FileChunk
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate
from backend.services.knowledge_base_service import build_chunk_vector_metadata, delete_file_knowledge_data
from backend.utils.vector_db_client import get_vector_db_client


class FileProcessorAgent(BaseAgent):
    """
    文件处理智能体

    功能：
    1. 识别文件类型
    2. 调用对应解析器提取内容
    3. 文档分块
    4. 向量化（待集成）
    5. 更新文件处理状态
    """

    def __init__(self):
        """初始化文件处理智能体"""
        super().__init__(
            agent_name="file_processor_agent",
            agent_type="file_processor"
        )

        # 初始化解析器
        self.parser_registry = get_parser_registry()
        self.parsers: Dict[str, BaseParser] = self.parser_registry.all()

        # 初始化分块器 - 从配置文件读取参数
        chunk_size = self._get_config_value("chunk_size", 1000)  # 与配置文件一致
        chunk_overlap = self._get_config_value("chunk_overlap", 100)
        self.chunker = DocumentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )

        # 初始化仓储
        self.file_repo = get_file_repository()
        self.chunk_repo = get_file_chunk_repository()
        self.execution_repo = get_agent_execution_repository()

        # 初始化向量存储
        try:
            self.vector_store = get_vector_db_client()
            self.vector_enabled = True
            self.logger.info("向量数据库客户端已启用")
        except Exception as e:
            self.logger.warning(f"向量数据库客户端不可用: {str(e)}")
            self.vector_store = None
            self.vector_enabled = False

        # 读取配置
        self.supported_formats = self._get_config_value("supported_formats", ["pdf", "docx", "xlsx", "txt", "md", "csv"])
        self.max_file_size = self._get_config_value("max_file_size", 50)  # MB

        self.logger.info(f"文件处理智能体初始化完成，支持的格式: {self.supported_formats}")
        self.logger.info(f"最大文件大小: {self.max_file_size}MB")

    def _get_parser_for_file(self, file_type: FileType) -> Optional[BaseParser]:
        """
        根据文件类型获取解析器

        Args:
            file_type: 文件类型

        Returns:
            解析器实例
        """
        parser_map = {
            FileType.PDF: "pdf",
            FileType.DOCX: "word",
            FileType.XLSX: "excel",
            FileType.TEXT: "text",
            FileType.MARKDOWN: "text",
            FileType.CODE: "text",
            FileType.JSON: "text",
            FileType.XML: "text"
        }

        parser_key = parser_map.get(file_type)
        if parser_key:
            return self.parser_registry.get(parser_key)

        return None

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
        metadata = {
            **(file.metadata or {}),
            "processing_stage": stage,
            "processing_progress": progress,
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

    async def process_file(self, file_id: str) -> Dict[str, Any]:
        """
        处理单个文件

        Args:
            file_id: 文件ID

        Returns:
            处理结果
        """
        try:
            # 1. 获取文件记录
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                return {
                    "success": False,
                    "error": f"文件不存在: {file_id}"
                }

            self.logger.info(f"Processing file: {file.original_filename} ({file.file_type})")

            # 2. 更新状态为处理中
            self._update_processing_progress(file, stage="queued", progress=5)

            # 3. 获取解析器
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

            # 4. 解析文件
            self._update_processing_progress(file, stage="parsing", progress=20)
            self.logger.info(f"Parsing file with {parser.__class__.__name__}")
            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "解析失败")
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

            # 5. 文档分块
            self._update_processing_progress(file, stage="chunking", progress=45)
            self.logger.info("Chunking document")
            chunks = []

            # 如果有分页信息，按页分块
            if parsed_content.pages:
                chunks = self.chunker.chunk_with_pages(
                    pages=parsed_content.pages,
                    base_metadata={
                        "file_id": file_id,
                        "filename": file.original_filename,
                        "file_type": file.file_type
                    }
                )
            else:
                # 否则直接分块
                chunks = self.chunker.chunk_text(
                    text=parsed_content.text,
                    metadata={
                        "file_id": file_id,
                        "filename": file.original_filename,
                        "file_type": file.file_type
                    }
                )

            self.logger.info(f"Created {len(chunks)} chunks")

            # 6. 保存分块到数据库
            self._update_processing_progress(file, stage="saving_chunks", progress=65)
            self.logger.info("Saving chunks to database")
            file_chunks = []
            for i, chunk in enumerate(chunks):
                file_chunk = FileChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_id=file_id,
                    chunk_index=i,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    metadata=chunk.metadata
                )
                file_chunks.append(file_chunk)

            # 批量保存分块
            cleanup_result = delete_file_knowledge_data(
                file_id=file_id,
                chunk_repo=self.chunk_repo,
                vector_store=self.vector_store if self.vector_enabled else None,
                log=self.logger,
            )
            if cleanup_result["chunk_count"] or cleanup_result["vector_count"]:
                self.logger.info(
                    f"Removed stale knowledge data before reprocessing: file_id={file_id}, "
                    f"chunks={cleanup_result['chunk_count']}, vectors={cleanup_result['vector_count']}"
                )

            if file_chunks:
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            # 7. 向量化并存入向量数据库
            vector_ids = []
            if self.vector_enabled and file_chunks:
                try:
                    self._update_processing_progress(file, stage="vectorizing", progress=80)
                    self.logger.info("开始向量化文本块...")

                    # 准备向量化数据
                    documents = [chunk.content for chunk in file_chunks]
                    metadatas = [build_chunk_vector_metadata(file, chunk) for chunk in file_chunks]
                    ids = [chunk.chunk_id for chunk in file_chunks]

                    # 生成向量嵌入
                    from backend.utils.embedding_client import get_embedding_client
                    embedding_client = get_embedding_client()
                    embeddings = embedding_client.embed_texts(documents)

                    # 过滤掉生成失败的嵌入
                    valid_data = [
                        (doc, emb, meta, id_)
                        for doc, emb, meta, id_ in zip(documents, embeddings, metadatas, ids)
                        if emb is not None
                    ]

                    if not valid_data:
                        self.logger.warning("所有文本块的向量生成都失败")
                    else:
                        valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)

                        # 添加到向量数据库
                        success = self.vector_store.add_documents(
                            documents=list(valid_documents),
                            embeddings=list(valid_embeddings),
                            metadatas=list(valid_metadatas),
                            ids=list(valid_ids)
                        )

                        if success:
                            vector_ids = list(valid_ids)
                            self.logger.info(f"成功向量化 {len(vector_ids)} 个文本块")

                            # 更新chunk的vector_id
                            for chunk in file_chunks:
                                if chunk.chunk_id in vector_ids:
                                    self.chunk_repo.update_chunk_vector_id(
                                        chunk.chunk_id,
                                        chunk.chunk_id  # 使用chunk_id作为vector_id
                                    )
                        else:
                            self.logger.warning("向量化失败")

                except Exception as e:
                    self.logger.error(f"Error during vectorization: {str(e)}", exc_info=True)

            # 8. 生成摘要（可选）
            self._update_processing_progress(file, stage="summarizing", progress=90)
            summary = await self._generate_summary(
                parsed_content,
                chunks,
                file.original_filename,
                file.file_type
            )

            # 9. 更新文件状态为完成
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
                        "processing_stage": "completed",
                        "processing_progress": 100,
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

            # 更新状态为失败
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
        生成文件摘要（使用LLM智能生成）

        Args:
            parsed_content: 解析后的内容
            chunks: 文本块列表
            filename: 文件名
            file_type: 文件类型

        Returns:
            摘要文本
        """
        try:
            # 获取文档元数据
            metadata = parsed_content.metadata
            total_pages = metadata.get("total_pages", 0)

            # 获取内容预览（前1000字符）
            text = parsed_content.text
            content_preview = text[:1000] if len(text) > 1000 else text

            # 使用提示词生成摘要
            summary_prompt = self._get_prompt(
                "summary_generation_prompt",
                filename=filename,
                file_type=file_type,
                total_pages=total_pages,
                chunk_count=len(chunks),
                content_preview=content_preview
            )

            if summary_prompt:
                # 调用LLM生成摘要
                messages = [
                    {
                        "role": "system",
                        "content": self._get_prompt("file_processor_system_prompt")
                    },
                    {
                        "role": "user",
                        "content": summary_prompt
                    }
                ]

                summary = await self.llm_client.chat_completion(
                    messages=messages,
                    temperature=0.5,
                    max_tokens=300
                )

                # 添加统计信息
                stats = self._build_stats_summary(metadata, len(chunks))
                if stats:
                    summary = f"[{stats}] {summary}"

                return summary
            else:
                # 降级到简单摘要
                return self._generate_simple_summary(parsed_content, chunks)

        except Exception as e:
            self.logger.error(f"Failed to generate LLM summary: {str(e)}")
            # 降级到简单摘要
            return self._generate_simple_summary(parsed_content, chunks)

    def _generate_simple_summary(self, parsed_content, chunks: List) -> str:
        """
        生成简单摘要（降级方案）

        Args:
            parsed_content: 解析后的内容
            chunks: 文本块列表

        Returns:
            摘要文本
        """
        # 简单摘要：提取前200字符
        text = parsed_content.text
        if len(text) > 200:
            summary = text[:200] + "..."
        else:
            summary = text

        # 添加统计信息
        metadata = parsed_content.metadata
        stats = self._build_stats_summary(metadata, len(chunks))
        if stats:
            summary = f"[{stats}] {summary}"

        return summary

    def _build_stats_summary(self, metadata: dict, chunk_count: int) -> str:
        """
        构建统计信息摘要

        Args:
            metadata: 文档元数据
            chunk_count: 文本块数量

        Returns:
            统计信息字符串
        """
        stats = []

        if "total_pages" in metadata:
            stats.append(f"{metadata['total_pages']}页")

        if "paragraph_count" in metadata:
            stats.append(f"{metadata['paragraph_count']}段")

        if "table_count" in metadata:
            stats.append(f"{metadata['table_count']}个表格")

        stats.append(f"{chunk_count}个文本块")

        return ', '.join(stats) if stats else ""

    def _get_error_message(self, error_type: str, **kwargs) -> str:
        """
        获取友好的错误提示信息

        Args:
            error_type: 错误类型
            **kwargs: 错误相关参数

        Returns:
            错误提示信息
        """
        error_prompt_key = f"error_handling.{error_type}"
        error_message = self._get_prompt(error_prompt_key, **kwargs)

        if error_message:
            return error_message

        # 默认错误信息
        return f"文件处理失败：{kwargs.get('error_message', '未知错误')}"

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        执行文件处理（非流式）

        Args:
            agent_input: 智能体输入，content应为file_id

        Returns:
            智能体输出
        """
        start_time = time.time()

        try:
            file_id = agent_input.content

            # 处理文件
            result = await self.process_file(file_id)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 保存执行记录
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
                    content=f"文件处理完成，生成了{result['chunk_count']}个文本块",
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
        执行文件处理（流式）

        Args:
            agent_input: 智能体输入

        Yields:
            流式数据块
        """
        try:
            file_id = agent_input.content

            # 发送开始状态
            yield StreamChunk.create_thinking("开始处理文件...")

            # 获取文件记录
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                yield StreamChunk.create_error(f"文件不存在: {file_id}")
                return

            yield StreamChunk.create_thinking(f"正在解析文件: {file.original_filename}")

            # 更新状态为处理中
            self.file_repo.update_file(
                file_id,
                FileUpdate(processing_status=ProcessingStatus.PROCESSING)
            )

            # 获取解析器
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

            # 解析文件
            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "解析失败")
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

            yield StreamChunk.create_thinking("正在分割文档...")

            # 文档分块
            if parsed_content.pages:
                chunks = self.chunker.chunk_with_pages(
                    pages=parsed_content.pages,
                    base_metadata={
                        "file_id": file_id,
                        "filename": file.original_filename,
                        "file_type": file.file_type
                    }
                )
            else:
                chunks = self.chunker.chunk_text(
                    text=parsed_content.text,
                    metadata={
                        "file_id": file_id,
                        "filename": file.original_filename,
                        "file_type": file.file_type
                    }
                )

            yield StreamChunk.create_thinking(f"已生成{len(chunks)}个文本块")

            # 保存分块到数据库
            yield StreamChunk.create_thinking("正在保存文本块...")
            file_chunks = []
            for i, chunk in enumerate(chunks):
                file_chunk = FileChunk(
                    chunk_id=str(uuid.uuid4()),
                    file_id=file_id,
                    chunk_index=i,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    metadata=chunk.metadata
                )
                file_chunks.append(file_chunk)

            # 批量保存分块
            cleanup_result = delete_file_knowledge_data(
                file_id=file_id,
                chunk_repo=self.chunk_repo,
                vector_store=self.vector_store if self.vector_enabled else None,
                log=self.logger,
            )
            if cleanup_result["chunk_count"] or cleanup_result["vector_count"]:
                self.logger.info(
                    f"Removed stale knowledge data before reprocessing: file_id={file_id}, "
                    f"chunks={cleanup_result['chunk_count']}, vectors={cleanup_result['vector_count']}"
                )

            if file_chunks:
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            # 向量化并存入向量数据库
            if self.vector_enabled and file_chunks:
                try:
                    yield StreamChunk.create_thinking("正在向量化文档...")

                    # 准备向量化数据
                    documents = [chunk.content for chunk in file_chunks]
                    metadatas = [build_chunk_vector_metadata(file, chunk) for chunk in file_chunks]
                    ids = [chunk.chunk_id for chunk in file_chunks]

                    # 生成向量嵌入
                    from backend.utils.embedding_client import get_embedding_client
                    embedding_client = get_embedding_client()
                    embeddings = embedding_client.embed_texts(documents)

                    # 过滤掉生成失败的嵌入
                    valid_data = [
                        (doc, emb, meta, id_)
                        for doc, emb, meta, id_ in zip(documents, embeddings, metadatas, ids)
                        if emb is not None
                    ]

                    if not valid_data:
                        self.logger.warning("所有文本块的向量生成都失败")
                        yield StreamChunk.create_thinking("向量生成失败")
                    else:
                        valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)

                        # 添加到向量数据库
                        success = self.vector_store.add_documents(
                            documents=list(valid_documents),
                            embeddings=list(valid_embeddings),
                            metadatas=list(valid_metadatas),
                            ids=list(valid_ids)
                        )

                        if success:
                            self.logger.info(f"成功向量化 {len(valid_ids)} 个文本块")
                            yield StreamChunk.create_thinking(f"已向量化{len(valid_ids)}个文本块")

                            # 更新chunk的vector_id
                            for chunk in file_chunks:
                                self.chunk_repo.update_chunk_vector_id(
                                    chunk.chunk_id,
                                    chunk.chunk_id  # 使用chunk_id作为vector_id
                                )
                        else:
                            self.logger.warning("Vectorization failed")
                            yield StreamChunk.create_thinking("向量化失败，但文件已成功处理")

                except Exception as e:
                    self.logger.error(f"Error during vectorization: {str(e)}", exc_info=True)
                    yield StreamChunk.create_thinking("向量化失败，但文件已成功处理")

            # 生成摘要
            yield StreamChunk.create_thinking("正在生成文档摘要...")
            summary = await self._generate_summary(
                parsed_content,
                chunks,
                file.original_filename,
                file.file_type
            )

            # 更新文件状态
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
                        "chunk_count": len(chunks)
                    }
                )
            )

            # 发送完成消息
            result_message = f"✅ 文件处理完成\n\n"
            result_message += f"📄 文件名: {file.original_filename}\n"
            result_message += f"📊 文本块数: {len(chunks)}\n"
            result_message += f"📝 摘要: {summary}\n"

            yield StreamChunk.create_content(result_message)

            # 保存执行记录
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
            yield StreamChunk.create_error(f"文件处理失败: {str(e)}")

    async def process_multiple_files(self, file_ids: List[str]) -> Dict[str, Any]:
        """
        批量处理多个文件

        Args:
            file_ids: 文件ID列表

        Returns:
            批量处理结果
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

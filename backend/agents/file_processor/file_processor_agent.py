# -*- coding: utf-8 -*-

"""
鏂囦欢澶勭悊 Agent 妯″潡锛岃礋璐ｈВ鏋愭枃浠躲€佸垏鍒嗘枃鏈€佷繚瀛樺垎鍧椼€佹墽琛屽彲閫夊悜閲忓寲骞剁敓鎴愭憳瑕併€?
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
from backend.file_processors import BaseParser, DocumentChunker, get_parser_registry
from backend.models.file import File, FileUpdate, ProcessingStatus, FileType, FileChunk
from backend.database.repositories.file_repository import get_file_repository
from backend.database.repositories.file_chunk_repository import get_file_chunk_repository
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate
from backend.domain.knowledge import build_chunk_vector_metadata, delete_file_knowledge_data
from backend.utils.vector_db_client import get_vector_db_client


class FileProcessorAgent(BaseAgent):
    """
    鏂囦欢澶勭悊 Agent锛岃礋璐ｄ覆鑱旀枃浠惰В鏋愩€佸垎鍧椼€佹寔涔呭寲銆佸悜閲忓寲鍜屾憳瑕佺敓鎴愮瓑鏍稿績姝ラ銆?
    """
    def __init__(self):
        """
        鍒濆鍖栨枃浠跺鐞?Agent锛屽苟鍑嗗瑙ｆ瀽鍣ㄣ€佸垎鍧楀櫒銆佷粨鍌ㄤ笌鍚戦噺搴撶瓑鎵ц渚濊禆銆?
        
        杩斿洖锛?
            鏃犺繑鍥炲€硷紱璇ユ柟娉曚粎瀹屾垚瀵硅薄鍐呴儴鐘舵€佸垵濮嬪寲銆?
        """
        super().__init__(
            agent_name="file_processor_agent",
            agent_type="file_processor"
        )

        # 鍒濆鍖栬В鏋愬櫒娉ㄥ唽琛紝骞跺姞杞界郴缁熷綋鍓嶅凡鏀寔鐨勬枃浠惰В鏋愬櫒銆?
        self.parser_registry = get_parser_registry()
        self.parsers: Dict[str, BaseParser] = self.parser_registry.all()

        chunk_size = self._get_config_value("chunk_size", 1000)  # 涓庨厤缃枃浠朵竴鑷?
        chunk_overlap = self._get_config_value("chunk_overlap", 100)
        # 鍒嗗潡绛栫暐闇€瑕佸拰宓屽叆妯″瀷鐨勬渶澶ц緭鍏ラ檺鍒跺榻愶紝閬垮厤鍚庣画鍚戦噺鍖栨椂鍗曞潡瓒呴暱銆?
        embedding_config = self.config_manager.get_model_config("embedding")
        embedding_max_input_tokens = int(embedding_config.get("max_input_tokens", 512) or 512)
        embedding_reserved_tokens = int(embedding_config.get("reserved_tokens", 32) or 32)
        chunk_token_limit = max(1, embedding_max_input_tokens - max(0, embedding_reserved_tokens))
        self.chunker = DocumentChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            max_chunk_tokens=chunk_token_limit,
        )

        # 鍒濆鍖栦粨鍌ㄥ璞★紝缁熶竴璐熻矗鏂囦欢銆佹枃鏈潡鍜屾墽琛岃褰曠殑鎸佷箙鍖栥€?
        self.file_repo = get_file_repository()
        self.chunk_repo = get_file_chunk_repository()
        self.execution_repo = get_agent_execution_repository()

        try:
            # 灏濊瘯杩炴帴鍚戦噺搴擄紱濡傛灉涓嶅彲鐢紝鍒欎粎璺宠繃鍚戦噺鍖栭樁娈碉紝涓嶉樆濉炰富娴佺▼銆?
            self.vector_store = get_vector_db_client()
            self.vector_enabled = True
            self.logger.info("File processor agent initialized")
        except Exception as e:
            self.logger.warning(f"鍚戦噺鏁版嵁搴撳鎴风涓嶅彲鐢? {str(e)}")
            self.vector_store = None
            self.vector_enabled = False

        # 璇诲彇鏂囦欢澶勭悊鐩稿叧閰嶇疆锛岄泦涓帶鍒舵敮鎸佹牸寮忓拰澶у皬闄愬埗銆?
        self.supported_formats = self._get_config_value("supported_formats", ["pdf", "docx", "xlsx", "txt", "md", "csv"])
        self.max_file_size = self._get_config_value("max_file_size", 50)  # MB

        self.logger.info(f"鏂囦欢澶勭悊鏅鸿兘浣撳垵濮嬪寲瀹屾垚锛屾敮鎸佺殑鏍煎紡: {self.supported_formats}")
        self.logger.info(f"鏈€澶ф枃浠跺ぇ灏? {self.max_file_size}MB")

    def _get_parser_for_file(self, file_type: FileType) -> Optional[BaseParser]:
        """
        鏍规嵁鏂囦欢绫诲瀷閫夋嫨瀵瑰簲鐨勮В鏋愬櫒瀹炵幇銆?
        
        鍙傛暟锛?
            file_type: 褰撳墠寰呭鐞嗘枃浠剁殑绫诲瀷鏋氫妇銆?
        
        杩斿洖锛?
            杩斿洖鍙敤瑙ｆ瀽鍣紱鑻ヨ绫诲瀷鏆備笉鏀寔锛屽垯杩斿洖 `None`銆?
        """
        parser_map = {
            FileType.PDF: "pdf",
            FileType.DOCX: "word",
            FileType.PPTX: "pptx",
            FileType.XLSX: "excel",
            FileType.HTML: "html",
            FileType.IMAGE: "image",
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
        """
        缁熶竴鏇存柊鏂囦欢澶勭悊闃舵銆佽繘搴︺€侀敊璇俊鎭笌鎵╁睍鍏冩暟鎹€?
        
        鍙傛暟锛?
            file: 褰撳墠姝ｅ湪澶勭悊鐨勬枃浠跺疄浣撱€?
            stage: 褰撳墠澶勭悊闃舵鏍囪瘑銆?
            progress: 褰撳墠闃舵瀵瑰簲鐨勮繘搴︾櫨鍒嗘瘮銆?
            status: 褰撳墠鏂囦欢闇€瑕佸啓鍥炵殑澶勭悊鐘舵€併€?
            error_message: 澶勭悊澶辫触鏃堕渶瑕佸啓鍥炵殑閿欒娑堟伅銆?
            extra_metadata: 闇€瑕侀澶栧悎骞跺啓鍥炵殑鍏冩暟鎹€?
        
        杩斿洖锛?
            鏃犺繑鍥炲€硷紱璇ユ柟娉曚細鐩存帴鏇存柊鏁版嵁搴撹褰曞拰鍐呭瓨涓殑鏂囦欢瀵硅薄銆?
        """
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
        澶勭悊鍗曚釜鏂囦欢鐨勫畬鏁寸敓鍛藉懆鏈燂細璇诲彇璁板綍銆佽В鏋愭枃浠躲€佸垏鍒嗗垎鍧椼€佷繚瀛樼粨鏋溿€佸悜閲忓寲骞剁敓鎴愭憳瑕併€?
        
        鍙傛暟锛?
            file_id: 寰呭鐞嗘枃浠剁殑鍞竴鏍囪瘑銆?
        
        杩斿洖锛?
            杩斿洖鍖呭惈鎴愬姛鏍囪銆侀敊璇俊鎭€佹憳瑕佸拰鍒嗗潡鏁伴噺鐨勭粨鏋勫寲缁撴灉瀛楀吀銆?
        """
        try:
            # 鍏堣鍙栨枃浠惰褰曪紝鍚庣画鐨勮В鏋愩€佸垎鍧椼€佸悜閲忓寲閮藉熀浜庤鏂囦欢瀹炰綋寮€灞曘€?
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                return {
                    "success": False,
                    "error": f"鏂囦欢涓嶅瓨鍦? {file_id}"
                }

            self.logger.info(f"Processing file: {file.original_filename} ({file.file_type})")

            # 浠诲姟鍚姩鍚庣珛鍗冲啓鍥炲垵濮嬭繘搴︼紝渚夸簬鍓嶇鎴栦换鍔＄郴缁熷強鏃舵劅鐭ョ姸鎬佸彉鍖栥€?
            self._update_processing_progress(file, stage="queued", progress=5)

            # 鏍规嵁鏂囦欢绫诲瀷閫夋嫨瑙ｆ瀽鍣紱鑻ユ病鏈夊彲鐢ㄥ疄鐜帮紝鍒欑洿鎺ヨ繑鍥炴槑纭敊璇€?
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
            # 瑙ｆ瀽鍘熷鏂囦欢锛屽緱鍒扮粨鏋勫寲鏂囨湰鍐呭鍙婂厓鏁版嵁淇℃伅銆?
            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "瑙ｆ瀽澶辫触")
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

            self._update_processing_progress(file, stage="chunking", progress=45)
            self.logger.info("Chunking document")
            # 灏嗚В鏋愮粨鏋滃垏鍒嗕负閫傚悎妫€绱㈠拰鍚戦噺鍖栫殑鏂囨湰鍧楋紝鎺у埗鍧楀ぇ灏忎笌閲嶅彔鑼冨洿銆?
            chunks = self.chunker.chunk_parsed_content(
                parsed_content=parsed_content,
                metadata={
                    "file_id": file_id,
                    "filename": file.original_filename,
                    "file_type": file.file_type,
                },
            )

            self.logger.info(f"Created {len(chunks)} chunks")

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

            # 閲嶆柊鍏ュ簱鍓嶅厛娓呯悊璇ユ枃浠舵棫鐨勬枃鏈潡鍜屽悜閲忥紝閬垮厤閲嶅绱㈠紩鍜岃剰鏁版嵁娈嬬暀銆?
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
                # 鎵归噺淇濆瓨鏂囨湰鍧楋紝涓哄悗缁绱€佸紩鐢ㄥ拰鍚戦噺鍖栨彁渚涚ǔ瀹氭暟鎹熀纭€銆?
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            vector_ids = []
            # 浠呭綋鍚戦噺搴撳彲鐢ㄤ笖瀛樺湪鏂囨湰鍧楁椂锛屾墠杩涘叆鍚戦噺鍖栭樁娈点€?
            if self.vector_enabled and file_chunks:
                try:
                    self._update_processing_progress(file, stage="vectorizing", progress=80)
                    self.logger.info("寮€濮嬪悜閲忓寲鏂囨湰鍧?..")

                    documents = [chunk.content for chunk in file_chunks]
                    metadatas = [build_chunk_vector_metadata(file, chunk) for chunk in file_chunks]
                    ids = [chunk.chunk_id for chunk in file_chunks]

                    from backend.utils.embedding_client import get_embedding_client
                    embedding_client = get_embedding_client()
                    embeddings = embedding_client.embed_texts(documents)

                    valid_data = [
                        (doc, emb, meta, id_)
                        for doc, emb, meta, id_ in zip(documents, embeddings, metadatas, ids)
                        if emb is not None
                    ]

                    if not valid_data:
                        self.logger.warning("鎵€鏈夋枃鏈潡鐨勫悜閲忕敓鎴愰兘澶辫触")
                    else:
                        valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)

                        success = self.vector_store.add_documents(
                            documents=list(valid_documents),
                            embeddings=list(valid_embeddings),
                            metadatas=list(valid_metadatas),
                            ids=list(valid_ids)
                        )

                        if success:
                            vector_ids = list(valid_ids)
                            self.logger.info(f"鎴愬姛鍚戦噺鍖?{len(vector_ids)} 涓枃鏈潡")

                            for chunk in file_chunks:
                                if chunk.chunk_id in vector_ids:
                                    self.chunk_repo.update_chunk_vector_id(
                                        chunk.chunk_id,
                                        chunk.chunk_id  # 浣跨敤chunk_id浣滀负vector_id
                                    )
                        else:
                            self.logger.warning("Vectorization returned no valid result")

                except Exception as e:
                    self.logger.error(f"Error during vectorization: {str(e)}", exc_info=True)

            self._update_processing_progress(file, stage="summarizing", progress=90)
            # 鍦ㄤ富澶勭悊娴佺▼瀹屾垚鍚庣敓鎴愭憳瑕侊紝渚夸簬鍒楄〃椤靛拰璇︽儏椤靛揩閫熷睍绀烘枃浠舵瑙堛€?
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
        鍩轰簬瑙ｆ瀽缁撴灉鍜屽垎鍧楀唴瀹圭敓鎴愭憳瑕侊紱浼樺厛浣跨敤妯″瀷鑳藉姏锛屽け璐ユ椂鍥為€€鍒扮畝鍗曟憳瑕併€?
        
        鍙傛暟锛?
            parsed_content: 瑙ｆ瀽鍣ㄨ緭鍑虹殑缁撴瀯鍖栧唴瀹广€?
            chunks: 鏂囨。鍒囧垎鍚庣殑鏂囨湰鍧楀垪琛ㄣ€?
            filename: 鍘熷鏂囦欢鍚嶃€?
            file_type: 鏂囦欢绫诲瀷瀛楃涓层€?
        
        杩斿洖锛?
            杩斿洖閫傚悎灞曠ず缁欑敤鎴风殑鎽樿鏂囨湰銆?
        """
        try:
            metadata = parsed_content.metadata
            total_pages = metadata.get("total_pages", 0)

            text = parsed_content.text
            content_preview = text[:1000] if len(text) > 1000 else text

            summary_prompt = self._get_prompt(
                "summary_generation_prompt",
                filename=filename,
                file_type=file_type,
                total_pages=total_pages,
                chunk_count=len(chunks),
                content_preview=content_preview
            )

            if summary_prompt:
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

                summary = await self.model_manager.invoke_messages(
                    messages=messages,
                    temperature=0.5,
                    max_tokens=300
                )

                stats = self._build_stats_summary(metadata, len(chunks))
                if stats:
                    summary = f"[{stats}] {summary}"

                return summary
            else:
                return self._generate_simple_summary(parsed_content, chunks)

        except Exception as e:
            self.logger.error(f"Failed to generate LLM summary: {str(e)}")
            return self._generate_simple_summary(parsed_content, chunks)

    def _generate_simple_summary(self, parsed_content, chunks: List) -> str:
        """
        鍦ㄦā鍨嬫憳瑕佷笉鍙敤鏃剁敓鎴愬厖搴曟憳瑕侊紝纭繚鏂囦欢澶勭悊涓绘祦绋嬩笉浼氬洜鎽樿澶辫触鑰屼腑鏂€?
        
        鍙傛暟锛?
            parsed_content: 瑙ｆ瀽鍣ㄨ緭鍑虹殑缁撴瀯鍖栧唴瀹广€?
            chunks: 鏂囨。鍒囧垎鍚庣殑鏂囨湰鍧楀垪琛ㄣ€?
        
        杩斿洖锛?
            杩斿洖绠€瑕佹憳瑕佹枃鏈€?
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
        鏍规嵁鍏冩暟鎹拰鍒嗗潡鏁伴噺鏋勫缓缁熻鍨嬫憳瑕併€?
        
        鍙傛暟锛?
            metadata: 瑙ｆ瀽闃舵鎻愬彇鐨勫厓鏁版嵁銆?
            chunk_count: 褰撳墠鏂囦欢鐨勬枃鏈潡鏁伴噺銆?
        
        杩斿洖锛?
            杩斿洖鍖呭惈椤垫暟銆佸瓧鏁版垨琛ㄦ牸鏁伴噺绛変俊鎭殑鎽樿鏂囨湰銆?
        """
        stats = []

        if "total_pages" in metadata:
            stats.append(f"{metadata['total_pages']} ?")

        if "paragraph_count" in metadata:
            stats.append(f"{metadata['paragraph_count']} ?")

        if "table_count" in metadata:
            stats.append(f"{metadata['table_count']} ??")

        stats.append(f"{chunk_count}涓枃鏈潡")

        return ', '.join(stats) if stats else ""

    def _get_error_message(self, error_type: str, **kwargs) -> str:
        """
        鏍规嵁閿欒绫诲瀷鐢熸垚缁熶竴鐨勪腑鏂囬敊璇彁绀恒€?
        
        鍙傛暟锛?
            error_type: 閿欒绫诲瀷鏍囪瘑銆?
            kwargs: 鐢熸垚閿欒鏂囨鏃堕渶瑕佽ˉ鍏呯殑鍔ㄦ€佸弬鏁般€?
        
        杩斿洖锛?
            杩斿洖闈㈠悜鐢ㄦ埛鎴栨棩蹇楄褰曠殑閿欒娑堟伅銆?
        """
        error_prompt_key = f"error_handling.{error_type}"
        error_message = self._get_prompt(error_prompt_key, **kwargs)

        if error_message:
            return error_message

        return f"File processing failed: {kwargs.get('error_message', 'unknown error')}"

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        鎵ц闈炴祦寮忔枃浠跺鐞嗭紝骞跺皢缁撴灉鍖呰涓虹粺涓€鐨?AgentOutput銆?
        
        鍙傛暟锛?
            agent_input: 缁熶竴灏佽鐨?Agent 杈撳叆瀵硅薄銆?
        
        杩斿洖锛?
            杩斿洖鍖呭惈澶勭悊鐘舵€併€佺粨鏋滃唴瀹瑰拰鍏冩暟鎹殑 AgentOutput銆?
        """
        start_time = time.time()

        try:
            file_id = getattr(agent_input, "file_id", None) or agent_input.content

            result = await self.process_file(file_id)

            execution_time_ms = int((time.time() - start_time) * 1000)

            # 鎸佷箙鍖栨湰娆?Agent 鎵ц璁板綍锛屼究浜庡璁°€佸洖婧笌鎺掗殰銆?
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
                    content=f"鏂囦欢澶勭悊瀹屾垚锛岀敓鎴愪簡{result['chunk_count']}涓枃鏈潡",
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
        鎵ц娴佸紡鏂囦欢澶勭悊锛屽湪涓嶅悓闃舵鎸佺画杈撳嚭杩涘害鍜岀粨鏋滀簨浠躲€?
        
        鍙傛暟锛?
            agent_input: 缁熶竴灏佽鐨?Agent 杈撳叆瀵硅薄銆?
        
        杩斿洖锛?
            浠ュ紓姝ョ敓鎴愬櫒褰㈠紡杩斿洖澶氫釜 `StreamChunk` 浜嬩欢銆?
        """
        try:
            file_id = getattr(agent_input, "file_id", None) or agent_input.content

            yield StreamChunk.create_thinking("寮€濮嬪鐞嗘枃浠?..")

            # 鍏堣鍙栨枃浠惰褰曪紝鍚庣画鐨勮В鏋愩€佸垎鍧椼€佸悜閲忓寲閮藉熀浜庤鏂囦欢瀹炰綋寮€灞曘€?
            file = self.file_repo.get_file_by_id(file_id)
            if not file:
                yield StreamChunk.create_error(f"鏂囦欢涓嶅瓨鍦? {file_id}")
                return

            yield StreamChunk.create_thinking(f"姝ｅ湪瑙ｆ瀽鏂囦欢: {file.original_filename}")

            self.file_repo.update_file(
                file_id,
                FileUpdate(processing_status=ProcessingStatus.PROCESSING)
            )

            # 鏍规嵁鏂囦欢绫诲瀷閫夋嫨瑙ｆ瀽鍣紱鑻ユ病鏈夊彲鐢ㄥ疄鐜帮紝鍒欑洿鎺ヨ繑鍥炴槑纭敊璇€?
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

            # 瑙ｆ瀽鍘熷鏂囦欢锛屽緱鍒扮粨鏋勫寲鏂囨湰鍐呭鍙婂厓鏁版嵁淇℃伅銆?
            parse_result = await parser.safe_parse(file.storage_path)

            if not parse_result["success"]:
                error_msg = parse_result.get("error", "瑙ｆ瀽澶辫触")
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

            yield StreamChunk.create_thinking("姝ｅ湪鍒嗗壊鏂囨。...")

            # 灏嗚В鏋愮粨鏋滃垏鍒嗕负閫傚悎妫€绱㈠拰鍚戦噺鍖栫殑鏂囨湰鍧楋紝鎺у埗鍧楀ぇ灏忎笌閲嶅彔鑼冨洿銆?
            chunks = self.chunker.chunk_parsed_content(
                parsed_content=parsed_content,
                metadata={
                    "file_id": file_id,
                    "filename": file.original_filename,
                    "file_type": file.file_type,
                },
            )

            yield StreamChunk.create_thinking(f"Generated {len(chunks)} chunks")

            yield StreamChunk.create_thinking("姝ｅ湪淇濆瓨鏂囨湰鍧?..")
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

            # 閲嶆柊鍏ュ簱鍓嶅厛娓呯悊璇ユ枃浠舵棫鐨勬枃鏈潡鍜屽悜閲忥紝閬垮厤閲嶅绱㈠紩鍜岃剰鏁版嵁娈嬬暀銆?
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
                # 鎵归噺淇濆瓨鏂囨湰鍧楋紝涓哄悗缁绱€佸紩鐢ㄥ拰鍚戦噺鍖栨彁渚涚ǔ瀹氭暟鎹熀纭€銆?
                self.chunk_repo.create_chunks_batch(file_chunks)
                self.logger.info(f"Saved {len(file_chunks)} chunks to database")

            # 浠呭綋鍚戦噺搴撳彲鐢ㄤ笖瀛樺湪鏂囨湰鍧楁椂锛屾墠杩涘叆鍚戦噺鍖栭樁娈点€?
            if self.vector_enabled and file_chunks:
                try:
                    yield StreamChunk.create_thinking("姝ｅ湪鍚戦噺鍖栨枃妗?..")

                    documents = [chunk.content for chunk in file_chunks]
                    metadatas = [build_chunk_vector_metadata(file, chunk) for chunk in file_chunks]
                    ids = [chunk.chunk_id for chunk in file_chunks]

                    from backend.utils.embedding_client import get_embedding_client
                    embedding_client = get_embedding_client()
                    embeddings = embedding_client.embed_texts(documents)

                    valid_data = [
                        (doc, emb, meta, id_)
                        for doc, emb, meta, id_ in zip(documents, embeddings, metadatas, ids)
                        if emb is not None
                    ]

                    if not valid_data:
                        self.logger.warning("鎵€鏈夋枃鏈潡鐨勫悜閲忕敓鎴愰兘澶辫触")
                        yield StreamChunk.create_thinking("鍚戦噺鐢熸垚澶辫触")
                    else:
                        valid_documents, valid_embeddings, valid_metadatas, valid_ids = zip(*valid_data)

                        success = self.vector_store.add_documents(
                            documents=list(valid_documents),
                            embeddings=list(valid_embeddings),
                            metadatas=list(valid_metadatas),
                            ids=list(valid_ids)
                        )

                        if success:
                            self.logger.info(f"鎴愬姛鍚戦噺鍖?{len(valid_ids)} 涓枃鏈潡")
                            yield StreamChunk.create_thinking(f"宸插悜閲忓寲{len(valid_ids)}涓枃鏈潡")

                            for chunk in file_chunks:
                                self.chunk_repo.update_chunk_vector_id(
                                    chunk.chunk_id,
                                    chunk.chunk_id  # 浣跨敤chunk_id浣滀负vector_id
                                )
                        else:
                            self.logger.warning("Vectorization failed")
                            yield StreamChunk.create_thinking("鍚戦噺鍖栧け璐ワ紝浣嗘枃浠跺凡鎴愬姛澶勭悊")

                except Exception as e:
                    self.logger.error(f"Error during vectorization: {str(e)}", exc_info=True)
                    yield StreamChunk.create_thinking("鍚戦噺鍖栧け璐ワ紝浣嗘枃浠跺凡鎴愬姛澶勭悊")

            yield StreamChunk.create_thinking("姝ｅ湪鐢熸垚鏂囨。鎽樿...")
            # 鍦ㄤ富澶勭悊娴佺▼瀹屾垚鍚庣敓鎴愭憳瑕侊紝渚夸簬鍒楄〃椤靛拰璇︽儏椤靛揩閫熷睍绀烘枃浠舵瑙堛€?
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
                        "chunk_count": len(chunks)
                    }
                )
            )

            result_message = f"鉁?鏂囦欢澶勭悊瀹屾垚\n\n"
            result_message += f"馃搫 鏂囦欢鍚? {file.original_filename}\n"
            result_message += f"馃搳 鏂囨湰鍧楁暟: {len(chunks)}\n"
            result_message += f"馃摑 鎽樿: {summary}\n"

            yield StreamChunk.create_content(result_message)

            # 鎸佷箙鍖栨湰娆?Agent 鎵ц璁板綍锛屼究浜庡璁°€佸洖婧笌鎺掗殰銆?
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
            yield StreamChunk.create_error(f"鏂囦欢澶勭悊澶辫触: {str(e)}")

    async def process_multiple_files(self, file_ids: List[str]) -> Dict[str, Any]:
        """
        鎵归噺澶勭悊澶氫釜鏂囦欢锛屽苟姹囨€绘瘡涓枃浠剁殑鎵ц缁撴灉銆?
        
        鍙傛暟锛?
            file_ids: 寰呮壒閲忓鐞嗙殑鏂囦欢 ID 鍒楄〃銆?
        
        杩斿洖锛?
            杩斿洖鍖呭惈鎬绘暟銆佹垚鍔熸暟銆佸け璐ユ暟鍜岄€愭枃浠跺鐞嗙粨鏋滅殑姹囨€诲瓧鍏搞€?
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


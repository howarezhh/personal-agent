"""
文件分块仓储
负责文件分块数据的CRUD操作
"""

import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime

from backend.database.database_manager import get_database_manager
from backend.models.file import FileChunk
from backend.utils.logger import get_logger

logger = get_logger(__name__)


class FileChunkRepository:
    """
    文件分块仓储类

    负责文件分块数据的数据库操作
    """

    def __init__(self):
        """初始化文件分块仓储"""
        self.db_manager = get_database_manager()

    def create_chunk(self, chunk: FileChunk) -> FileChunk:
        """
        创建文件分块记录

        Args:
            chunk: 文件分块对象

        Returns:
            创建的文件分块对象
        """
        try:
            query = """
                INSERT INTO file_chunks (
                    chunk_id, file_id, chunk_index, content,
                    page_number, start_char, end_char, token_count,
                    vector_id, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            # 提取metadata
            metadata = chunk.metadata
            if metadata:
                import json
                metadata = json.dumps(metadata)

            params = (
                chunk.chunk_id,
                chunk.file_id,
                chunk.chunk_index,
                chunk.content,
                chunk.metadata.get('page_number') if chunk.metadata else None,
                chunk.metadata.get('start_char') if chunk.metadata else None,
                chunk.metadata.get('end_char') if chunk.metadata else None,
                chunk.metadata.get('token_count') if chunk.metadata else None,
                chunk.metadata.get('vector_id') if chunk.metadata else None,
                metadata
            )

            self.db_manager.execute_update(query, params)
            logger.info(f"File chunk created: {chunk.chunk_id}")

            return chunk

        except Exception as e:
            logger.error(f"Error creating file chunk: {str(e)}", exc_info=True)
            raise

    def create_chunks_batch(self, chunks: List[FileChunk]) -> int:
        """
        批量创建文件分块记录

        Args:
            chunks: 文件分块列表

        Returns:
            创建的记录数
        """
        try:
            if not chunks:
                return 0

            query = """
                INSERT INTO file_chunks (
                    chunk_id, file_id, chunk_index, content,
                    page_number, start_char, end_char, token_count,
                    vector_id, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            import json
            params_list = []
            for chunk in chunks:
                metadata = chunk.metadata
                if metadata:
                    metadata = json.dumps(metadata)

                params = (
                    chunk.chunk_id,
                    chunk.file_id,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.metadata.get('page_number') if chunk.metadata else None,
                    chunk.metadata.get('start_char') if chunk.metadata else None,
                    chunk.metadata.get('end_char') if chunk.metadata else None,
                    chunk.metadata.get('token_count') if chunk.metadata else None,
                    chunk.metadata.get('vector_id') if chunk.metadata else None,
                    metadata
                )
                params_list.append(params)

            # 批量插入
            for params in params_list:
                self.db_manager.execute_update(query, params)

            logger.info(f"Created {len(chunks)} file chunks in batch")
            return len(chunks)

        except Exception as e:
            logger.error(f"Error creating file chunks in batch: {str(e)}", exc_info=True)
            raise

    def get_chunk_by_id(self, chunk_id: str) -> Optional[FileChunk]:
        """
        根据ID获取文件分块

        Args:
            chunk_id: 分块ID

        Returns:
            文件分块对象，不存在则返回None
        """
        try:
            query = """
                SELECT chunk_id, file_id, chunk_index, content,
                       page_number, start_char, end_char, token_count,
                       vector_id, created_at, metadata
                FROM file_chunks
                WHERE chunk_id = %s
            """

            result = self.db_manager.execute_query(query, (chunk_id,))

            if result:
                row = result[0]
                return self._row_to_chunk(row)

            return None

        except Exception as e:
            logger.error(f"Error getting file chunk by id: {str(e)}", exc_info=True)
            raise

    def get_chunks_by_file_id(
        self,
        file_id: str,
        limit: Optional[int] = 100,
        offset: int = 0
    ) -> List[FileChunk]:
        """
        根据文件ID获取所有分块

        Args:
            file_id: 文件ID
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            文件分块列表
        """
        try:
            if limit is None:
                query = """
                    SELECT chunk_id, file_id, chunk_index, content,
                           page_number, start_char, end_char, token_count,
                           vector_id, created_at, metadata
                    FROM file_chunks
                    WHERE file_id = %s
                    ORDER BY chunk_index ASC
                """
                results = self.db_manager.execute_query(query, (file_id,))
            else:
                query = """
                    SELECT chunk_id, file_id, chunk_index, content,
                           page_number, start_char, end_char, token_count,
                           vector_id, created_at, metadata
                    FROM file_chunks
                    WHERE file_id = %s
                    ORDER BY chunk_index ASC
                    LIMIT %s OFFSET %s
                """
                results = self.db_manager.execute_query(query, (file_id, limit, offset))

            chunks = []
            for row in results:
                chunk = self._row_to_chunk(row)
                if chunk:
                    chunks.append(chunk)

            return chunks

        except Exception as e:
            logger.error(f"Error getting file chunks by file_id: {str(e)}", exc_info=True)
            raise

    def update_chunk_vector_id(self, chunk_id: str, vector_id: str) -> bool:
        """
        更新分块的向量ID

        Args:
            chunk_id: 分块ID
            vector_id: 向量数据库中的ID

        Returns:
            是否更新成功
        """
        try:
            query = """
                UPDATE file_chunks
                SET vector_id = %s
                WHERE chunk_id = %s
            """

            rows_affected = self.db_manager.execute_update(query, (vector_id, chunk_id))
            logger.info(f"Updated vector_id for chunk: {chunk_id}")

            return rows_affected > 0

        except Exception as e:
            logger.error(f"Error updating chunk vector_id: {str(e)}", exc_info=True)
            raise

    def delete_chunks_by_file_id(self, file_id: str) -> int:
        """
        删除文件的所有分块

        Args:
            file_id: 文件ID

        Returns:
            删除的记录数
        """
        try:
            query = "DELETE FROM file_chunks WHERE file_id = %s"
            rows_affected = self.db_manager.execute_update(query, (file_id,))

            logger.info(f"Deleted {rows_affected} chunks for file: {file_id}")
            return rows_affected

        except Exception as e:
            logger.error(f"Error deleting file chunks: {str(e)}", exc_info=True)
            raise

    def get_chunk_count_by_file_id(self, file_id: str) -> int:
        """
        获取文件的分块数量

        Args:
            file_id: 文件ID

        Returns:
            分块数量
        """
        try:
            query = "SELECT COUNT(*) as count FROM file_chunks WHERE file_id = %s"
            result = self.db_manager.execute_query(query, (file_id,))

            if result:
                return result[0][0]

            return 0

        except Exception as e:
            logger.error(f"Error getting chunk count: {str(e)}", exc_info=True)
            raise

    def search_chunks_by_content(
        self,
        file_id: str,
        search_text: str,
        limit: int = 10
    ) -> List[FileChunk]:
        """
        在文件分块中搜索内容

        Args:
            file_id: 文件ID
            search_text: 搜索文本
            limit: 返回数量限制

        Returns:
            匹配的文件分块列表
        """
        try:
            query = """
                SELECT chunk_id, file_id, chunk_index, content,
                       page_number, start_char, end_char, token_count,
                       vector_id, created_at, metadata
                FROM file_chunks
                WHERE file_id = %s AND content LIKE %s
                ORDER BY chunk_index ASC
                LIMIT %s
            """

            search_pattern = f"%{search_text}%"
            results = self.db_manager.execute_query(
                query,
                (file_id, search_pattern, limit)
            )

            chunks = []
            for row in results:
                chunk = self._row_to_chunk(row)
                if chunk:
                    chunks.append(chunk)

            return chunks

        except Exception as e:
            logger.error(f"Error searching chunks: {str(e)}", exc_info=True)
            raise

    def _row_to_chunk(self, row: tuple) -> Optional[FileChunk]:
        """
        将数据库行转换为FileChunk对象

        Args:
            row: 数据库行

        Returns:
            FileChunk对象
        """
        try:
            import json

            metadata = {}
            if row[10]:  # metadata字段
                if isinstance(row[10], str):
                    metadata = json.loads(row[10])
                else:
                    metadata = row[10]

            # 添加其他字段到metadata
            if row[4] is not None:  # page_number
                metadata['page_number'] = row[4]
            if row[5] is not None:  # start_char
                metadata['start_char'] = row[5]
            if row[6] is not None:  # end_char
                metadata['end_char'] = row[6]
            if row[7] is not None:  # token_count
                metadata['token_count'] = row[7]
            if row[8] is not None:  # vector_id
                metadata['vector_id'] = row[8]

            return FileChunk(
                chunk_id=row[0],
                file_id=row[1],
                chunk_index=row[2],
                content=row[3],
                page_number=row[4],
                start_char=row[5],
                end_char=row[6],
                token_count=row[7],
                vector_id=row[8],
                created_at=row[9],
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Error converting row to FileChunk: {str(e)}", exc_info=True)
            return None


# 单例模式
_file_chunk_repository = None


def get_file_chunk_repository() -> FileChunkRepository:
    """
    获取文件分块仓储单例

    Returns:
        FileChunkRepository实例
    """
    global _file_chunk_repository
    if _file_chunk_repository is None:
        _file_chunk_repository = FileChunkRepository()
    return _file_chunk_repository

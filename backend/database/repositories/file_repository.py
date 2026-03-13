"""
文件数据库仓储
负责文件记录的数据库操作
"""

from typing import List, Optional
from datetime import datetime
import json
from backend.database.repositories.user_repository import BaseRepository
from backend.database.database_manager import DatabaseManager, get_database_manager
from backend.models.file import File, FileCreate, FileUpdate, FileType, ProcessingStatus
from backend.utils.logger import get_logger


logger = get_logger(__name__)


class FileRepository(BaseRepository):
    """
    文件仓储类

    功能：
    1. 文件记录CRUD操作
    2. 用户文件查询
    3. 文件统计
    """

    TABLE_NAME = "files"

    def create_file(self, file_create: FileCreate) -> File:
        """
        创建文件记录

        Args:
            file_create: 文件创建数据

        Returns:
            创建的文件对象

        Raises:
            ValueError: 数据验证失败
            Exception: 数据库操作失败
        """
        # 验证数据
        is_valid, error_msg = file_create.validate()
        if not is_valid:
            raise ValueError(error_msg)

        # 转换为File对象
        file = file_create.to_file()

        # 插入数据库
        data = {
            "file_id": file.file_id,
            "user_id": file.user_id,
            "conversation_id": file.conversation_id,
            "original_filename": file.original_filename,
            "file_type": file.file_type if isinstance(file.file_type, str) else file.file_type.value,
            "file_size": file.file_size,
            "storage_path": file.storage_path,
            "processing_status": file.processing_status if isinstance(file.processing_status, str) else file.processing_status.value,
            "created_at": file.created_at,
            "updated_at": file.updated_at,
            "metadata": json.dumps(file.metadata, ensure_ascii=False) if file.metadata else None,
        }

        self.db.insert_one(self.TABLE_NAME, data, return_id=False)

        logger.info(
            f"File created: file_id={file.file_id}, "
            f"filename={file.original_filename}, type={file.file_type}"
        )
        return file

    def update_file(self, file_id: str, file_update: FileUpdate) -> bool:
        """
        更新文件记录

        Args:
            file_id: 文件ID
            file_update: 更新数据

        Returns:
            是否更新成功

        Raises:
            ValueError: 文件不存在
            Exception: 数据库操作失败
        """
        # 检查文件是否存在
        if not self.exists_by_id(file_id):
            raise ValueError(f"文件不存在: file_id={file_id}")

        # 构建更新数据
        update_data = file_update.to_dict()
        if not update_data:
            logger.warning("No data to update")
            return False

        # 处理枚举类型
        if "processing_status" in update_data:
            value = update_data["processing_status"]
            update_data["processing_status"] = value.value if isinstance(value, ProcessingStatus) else value

        if "metadata" in update_data and update_data["metadata"]:
            update_data["metadata"] = json.dumps(update_data["metadata"], ensure_ascii=False)

        # 添加更新时间
        update_data["updated_at"] = datetime.utcnow()

        # 执行更新
        affected_rows = self.db.update_one(
            table=self.TABLE_NAME,
            data=update_data,
            where={"file_id": file_id}
        )

        logger.info(
            f"File updated: file_id={file_id}, "
            f"fields={list(update_data.keys())}"
        )
        return affected_rows > 0

    def get_file_by_id(self, file_id: str) -> Optional[File]:
        """
        根据ID获取文件记录

        Args:
            file_id: 文件ID

        Returns:
            文件对象，如果不存在返回None
        """
        result = self.db.select_one(
            table=self.TABLE_NAME,
            where={"file_id": file_id}
        )
        return self._dict_to_model(result, File)

    def get_files_by_user_id(
        self,
        user_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> List[File]:
        """
        根据用户ID获取文件列表

        Args:
            user_id: 用户ID
            limit: 限制返回数量
            offset: 偏移量

        Returns:
            文件列表
        """
        results = self.db.select_many(
            table=self.TABLE_NAME,
            where={"user_id": user_id},
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        return self._dicts_to_models(results, File)

    def get_files_by_conversation_id(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        user_id: Optional[str] = None,
    ) -> List[File]:
        """Get files by conversation id with optional user filter."""
        where = {"conversation_id": conversation_id}
        if user_id:
            where["user_id"] = user_id

        results = self.db.select_many(
            table=self.TABLE_NAME,
            where=where,
            order_by="created_at DESC",
            limit=limit,
            offset=offset,
        )

        logger.info(
            f"按会话查询文件完成: conversation_id={conversation_id}, user_id={user_id}, "
            f"limit={limit}, offset={offset}, count={len(results)}"
        )

        return self._dicts_to_models(results, File)


    def delete_file(self, file_id: str) -> bool:
        """
        删除文件记录

        Args:
            file_id: 文件ID

        Returns:
            是否删除成功

        Raises:
            ValueError: 文件不存在
            Exception: 数据库操作失败
        """
        # 检查文件是否存在
        if not self.exists_by_id(file_id):
            raise ValueError(f"文件不存在: file_id={file_id}")

        # 物理删除记录
        affected_rows = self.db.delete_one(
            table=self.TABLE_NAME,
            where={"file_id": file_id}
        )

        logger.info(f"File deleted: file_id={file_id}")
        return affected_rows > 0

    def exists_by_id(self, file_id: str) -> bool:
        """
        检查文件ID是否存在

        Args:
            file_id: 文件ID

        Returns:
            是否存在
        """
        return self.db.exists(self.TABLE_NAME, {"file_id": file_id})

    def get_file_count_by_user(self, user_id: str) -> int:
        """
        统计用户的文件数量

        Args:
            user_id: 用户ID

        Returns:
            文件数量
        """
        return self.db.count(self.TABLE_NAME, {"user_id": user_id})

    def get_file_count_by_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> int:
        """统计指定会话下的文件数量。"""
        where = {"conversation_id": conversation_id}
        if user_id:
            where["user_id"] = user_id

        return self.db.count(self.TABLE_NAME, where)

    def get_file_statistics(self, user_id: Optional[str] = None) -> dict:
        """
        获取文件统计信息

        Args:
            user_id: 用户ID（可选），如果指定则只统计该用户

        Returns:
            统计信息字典
        """
        if user_id:
            sql = """
                SELECT
                    COUNT(*) as total_files,
                    SUM(file_size) as total_size,
                    SUM(CASE WHEN processing_status = 'completed' THEN 1 ELSE 0 END) as completed_files,
                    SUM(CASE WHEN processing_status = 'failed' THEN 1 ELSE 0 END) as failed_files
                FROM files
                WHERE user_id = %s
            """
            params = (user_id,)
        else:
            sql = """
                SELECT
                    COUNT(*) as total_files,
                    SUM(file_size) as total_size,
                    SUM(CASE WHEN processing_status = 'completed' THEN 1 ELSE 0 END) as completed_files,
                    SUM(CASE WHEN processing_status = 'failed' THEN 1 ELSE 0 END) as failed_files
                FROM files
            """
            params = None

        result = self.db.execute_query(sql, params, fetch_one=True)

        if result:
            return {
                "total_files": result.get("total_files", 0) or 0,
                "total_size": result.get("total_size", 0) or 0,
                "completed_files": result.get("completed_files", 0) or 0,
                "failed_files": result.get("failed_files", 0) or 0,
            }

        return {
            "total_files": 0,
            "total_size": 0,
            "completed_files": 0,
            "failed_files": 0,
        }


# 全局仓储实例
_file_repository: Optional[FileRepository] = None


def get_file_repository() -> FileRepository:
    """
    获取全局文件仓储实例（单例模式）

    Returns:
        FileRepository实例
    """
    global _file_repository

    if _file_repository is None:
        _file_repository = FileRepository()

    return _file_repository

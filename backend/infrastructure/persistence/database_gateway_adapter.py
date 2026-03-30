from __future__ import annotations

from backend.database.database_manager import get_database_manager


class DatabaseGatewayAdapter:
    """数据库管理器适配器，供应用层通过统一入口使用。"""

    def __init__(self, database_manager=None):
        self.database_manager = database_manager or get_database_manager()

    def execute_query(self, *args, **kwargs):
        return self.database_manager.execute_query(*args, **kwargs)

    def execute_update(self, *args, **kwargs):
        return self.database_manager.execute_update(*args, **kwargs)

    def close(self):
        return self.database_manager.close()

    def test_connection(self):
        return self.database_manager.test_connection()

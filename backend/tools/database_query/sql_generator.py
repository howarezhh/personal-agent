
from typing import Dict, Any, Optional
from backend.utils.llm_client import get_llm_client
from backend.utils.logger import get_logger
from backend.core.prompt_manager import get_prompt_manager


class SQLGenerator:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)
        self.llm_client = get_llm_client()
        self.prompt_manager = get_prompt_manager()
        
        # 允许的SQL操作（只读操作）
        self.allowed_operations = ["SELECT"]
        
        # 危险关键词（防止SQL注入）
        self.dangerous_keywords = [
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
            "CREATE", "TRUNCATE", "EXEC", "EXECUTE"
        ]
    
    async def generate_sql(
        self,
        natural_language_query: str,
        schema_info: Dict[str, Any],
        database_type: str = "mysql"
    ) -> Dict[str, Any]:
        try:
            self.logger.info(f"开始生成SQL: 查询={natural_language_query}, 数据库类型={database_type}")

            # 构建提示词
            prompt = self._build_prompt(
                natural_language_query,
                schema_info,
                database_type
            )

            # 调用LLM生成SQL
            messages = [
                {
                    "role": "system",
                    "content": self.prompt_manager.get_prompt("tool.database_query_system_prompt")
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            self.logger.debug("调用LLM生成SQL查询")
            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=500
            )

            # 提取SQL查询
            sql_query = self._extract_sql(response)
            self.logger.debug(f"生成的SQL: {sql_query}")

            # 验证SQL安全性
            is_safe, reason = self._validate_sql_safety(sql_query)

            if not is_safe:
                self.logger.warning(f"SQL查询不安全: {reason}")
                return {
                    "success": False,
                    "error": f"不安全的SQL查询: {reason}",
                    "sql": sql_query
                }

            self.logger.info("SQL生成成功")
            return {
                "success": True,
                "sql": sql_query,
                "database_type": database_type,
                "natural_language_query": natural_language_query
            }

        except Exception as e:
            self.logger.error(f"生成SQL失败: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _build_prompt(
        self,
        query: str,
        schema_info: Dict[str, Any],
        database_type: str
    ) -> str:
        schema_str = self._format_schema(schema_info)
        return self.prompt_manager.format_prompt(
            "tool.database_query_sql_generation_prompt",
            schema_info=schema_str,
            database_type=database_type,
            query=query,
        )
    
    def _format_schema(self, schema_info: Dict[str, Any]) -> str:
        lines = []
        
        for table_name, table_info in schema_info.items():
            lines.append(f"Table: {table_name}")
            
            if "columns" in table_info:
                lines.append("Columns:")
                for col in table_info["columns"]:
                    lines.append(f"  - {col['name']} ({col['type']})")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def _extract_sql(self, response: str) -> str:
        # 移除代码块标记
        sql = response.strip()
        
        if "```sql" in sql:
            start = sql.find("```sql") + 6
            end = sql.find("```", start)
            sql = sql[start:end].strip()
        elif "```" in sql:
            start = sql.find("```") + 3
            end = sql.find("```", start)
            sql = sql[start:end].strip()
        
        return sql
    
    def _validate_sql_safety(self, sql: str) -> tuple[bool, Optional[str]]:
        sql_upper = sql.upper()

        # 检查是否包含危险关键词
        for keyword in self.dangerous_keywords:
            if keyword in sql_upper:
                return False, f"包含危险关键词: {keyword}"

        # 检查是否是SELECT查询
        if not sql_upper.strip().startswith("SELECT"):
            return False, "只允许SELECT查询"

        # 检查是否包含分号（防止多语句注入）
        if ";" in sql[:-1]:  # 允许末尾的分号
            return False, "不允许多条语句"

        return True, None

-- 迁移脚本：让 agent_executions 表的 conversation_id 字段可为空
-- 用于支持直接工具调用（不需要会话上下文）
-- 创建时间：2026-02-12

USE personal_agent;

-- 修改 agent_executions 表，让 conversation_id 可为 NULL
ALTER TABLE agent_executions
MODIFY COLUMN conversation_id VARCHAR(36) NULL COMMENT '会话ID (可为空，直接工具调用时为NULL)';

-- 验证修改
SELECT
    COLUMN_NAME,
    IS_NULLABLE,
    COLUMN_TYPE,
    COLUMN_COMMENT
FROM
    INFORMATION_SCHEMA.COLUMNS
WHERE
    TABLE_SCHEMA = 'personal_agent'
    AND TABLE_NAME = 'agent_executions'
    AND COLUMN_NAME = 'conversation_id';

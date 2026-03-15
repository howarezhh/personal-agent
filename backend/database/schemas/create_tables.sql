-- 本文件使用 UTF-8 编码，请使用支持 UTF-8 的编辑器查看和执行。
-- ============================================
-- 企业级多Agent知识库助手 - 数据库表结构
-- 数据库类型: MySQL
-- 字符集: utf8mb4
-- 创建时间: 2024-01-01
-- ============================================

-- 设置字符集
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================
-- 1. 用户表 (users)
-- 存储用户基本信息
-- ============================================
CREATE TABLE IF NOT EXISTS `users` (
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID (UUID)',
    `username` VARCHAR(50) NOT NULL COMMENT '用户名',
    `email` VARCHAR(100) NOT NULL COMMENT '邮箱',
    `password_hash` VARCHAR(255) NOT NULL COMMENT '密码哈希值',
    `full_name` VARCHAR(100) DEFAULT NULL COMMENT '全名',
    `avatar_url` VARCHAR(255) DEFAULT NULL COMMENT '头像URL',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否激活 (1=激活, 0=禁用)',
    `is_admin` TINYINT(1) DEFAULT 0 COMMENT '是否管理员 (1=是, 0=否)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `last_login_at` TIMESTAMP NULL DEFAULT NULL COMMENT '最后登录时间',
    PRIMARY KEY (`user_id`),
    UNIQUE KEY `uk_username` (`username`),
    UNIQUE KEY `uk_email` (`email`),
    KEY `idx_is_active` (`is_active`),
    KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ============================================
-- 2. 会话表 (conversations)
-- 存储用户的对话会话
-- ============================================
CREATE TABLE IF NOT EXISTS `conversations` (
    `conversation_id` VARCHAR(36) NOT NULL COMMENT '会话ID (UUID)',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `title` VARCHAR(200) DEFAULT '新对话' COMMENT '会话标题',
    `description` TEXT DEFAULT NULL COMMENT '会话描述',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否激活 (1=激活, 0=已删除)',
    `message_count` INT DEFAULT 0 COMMENT '消息数量',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`conversation_id`),
    KEY `idx_user_id` (`user_id`),
    KEY `idx_is_active` (`is_active`),
    KEY `idx_updated_at` (`updated_at`),
    KEY `idx_user_updated` (`user_id`, `updated_at`),
    CONSTRAINT `fk_conversations_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话表';

-- ============================================
-- 3. 知识库表 (knowledge_bases)
-- 存储用户创建的知识库
-- ============================================
CREATE TABLE IF NOT EXISTS `knowledge_bases` (
    `knowledge_base_id` VARCHAR(36) NOT NULL COMMENT '知识库ID (UUID)',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `name` VARCHAR(100) NOT NULL COMMENT '知识库名称',
    `description` TEXT DEFAULT NULL COMMENT '知识库描述',
    `is_default` TINYINT(1) DEFAULT 0 COMMENT '是否默认知识库 (1=是, 0=否)',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否激活 (1=激活, 0=已删除)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`knowledge_base_id`),
    KEY `idx_kb_user_active_created` (`user_id`, `is_active`, `created_at`),
    KEY `idx_kb_user_default` (`user_id`, `is_default`),
    KEY `idx_kb_user_name` (`user_id`, `name`),
    CONSTRAINT `fk_knowledge_bases_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- ============================================
-- 4. 消息表 (messages)
-- 存储对话消息（用户消息和助手回复）
-- ============================================
CREATE TABLE IF NOT EXISTS `messages` (
    `message_id` VARCHAR(36) NOT NULL COMMENT '消息ID (UUID)',
    `conversation_id` VARCHAR(36) NOT NULL COMMENT '会话ID',
    `message_type` ENUM('user', 'assistant', 'system') NOT NULL COMMENT '消息类型',
    `content` TEXT NOT NULL COMMENT '消息内容',
    `sequence_number` INT NOT NULL COMMENT '消息序号 (从1开始)',
    `parent_message_id` VARCHAR(36) DEFAULT NULL COMMENT '父消息ID (用于分支对话)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`message_id`),
    KEY `idx_conversation_id` (`conversation_id`),
    KEY `idx_conversation_sequence` (`conversation_id`, `sequence_number`),
    KEY `idx_message_type` (`message_type`),
    KEY `idx_created_at` (`created_at`),
    CONSTRAINT `fk_messages_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息表';

-- ============================================
-- 5. 智能体执行记录表 (agent_executions)
-- 存储每次智能体执行的详细记录
-- ============================================
CREATE TABLE IF NOT EXISTS `agent_executions` (
    `execution_id` VARCHAR(36) NOT NULL COMMENT '执行ID (UUID)',
    `conversation_id` VARCHAR(36) DEFAULT NULL COMMENT '会话ID (可为空，直接工具调用时为NULL)',
    `message_id` VARCHAR(36) DEFAULT NULL COMMENT '关联的消息ID',
    `agent_name` VARCHAR(100) NOT NULL COMMENT '智能体名称',
    `agent_type` ENUM('router', 'retrieval', 'generation', 'tool', 'file_processor') NOT NULL COMMENT '智能体类型',
    `input_data` JSON DEFAULT NULL COMMENT '输入数据 (JSON格式)',
    `output_data` JSON DEFAULT NULL COMMENT '输出数据 (JSON格式)',
    `status` ENUM('success', 'failed', 'partial', 'running') DEFAULT 'running' COMMENT '执行状态',
    `error_message` TEXT DEFAULT NULL COMMENT '错误信息',
    `execution_time_ms` INT DEFAULT NULL COMMENT '执行时间 (毫秒)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `completed_at` TIMESTAMP NULL DEFAULT NULL COMMENT '完成时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`execution_id`),
    KEY `idx_conversation_id` (`conversation_id`),
    KEY `idx_message_id` (`message_id`),
    KEY `idx_agent_name` (`agent_name`),
    KEY `idx_agent_type` (`agent_type`),
    KEY `idx_status` (`status`),
    KEY `idx_created_at` (`created_at`),
    CONSTRAINT `fk_executions_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE,
    CONSTRAINT `fk_executions_message` FOREIGN KEY (`message_id`) REFERENCES `messages` (`message_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体执行记录表';

-- ============================================
-- 6. 检索结果表 (retrieval_results)
-- 存储检索智能体的检索结果
-- ============================================
CREATE TABLE IF NOT EXISTS `retrieval_results` (
    `result_id` VARCHAR(36) NOT NULL COMMENT '结果ID (UUID)',
    `execution_id` VARCHAR(36) NOT NULL COMMENT '执行ID',
    `source_type` VARCHAR(50) DEFAULT NULL COMMENT '来源类型 (document/database/api等)',
    `source_id` VARCHAR(255) DEFAULT NULL COMMENT '来源ID',
    `source_name` VARCHAR(255) DEFAULT NULL COMMENT '来源名称',
    `content` TEXT NOT NULL COMMENT '检索到的内容',
    `relevance_score` FLOAT DEFAULT NULL COMMENT '相关度分数 (0-1)',
    `rank_position` INT DEFAULT NULL COMMENT '排序位置',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`result_id`),
    KEY `idx_execution_id` (`execution_id`),
    KEY `idx_source_type` (`source_type`),
    KEY `idx_relevance_score` (`relevance_score`),
    KEY `idx_rank_position` (`rank_position`),
    CONSTRAINT `fk_retrieval_execution` FOREIGN KEY (`execution_id`) REFERENCES `agent_executions` (`execution_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='检索结果表';

-- ============================================
-- 7. 工具调用表 (tool_calls)
-- 存储工具调用的详细记录
-- ============================================
CREATE TABLE IF NOT EXISTS `tool_calls` (
    `call_id` VARCHAR(36) NOT NULL COMMENT '调用ID (UUID)',
    `execution_id` VARCHAR(36) NOT NULL COMMENT '执行ID',
    `tool_name` VARCHAR(100) NOT NULL COMMENT '工具名称',
    `tool_type` VARCHAR(50) DEFAULT NULL COMMENT '工具类型',
    `tool_input` JSON DEFAULT NULL COMMENT '工具输入 (JSON格式)',
    `tool_output` JSON DEFAULT NULL COMMENT '工具输出 (JSON格式)',
    `status` ENUM('success', 'failed', 'timeout', 'running') DEFAULT 'running' COMMENT '调用状态',
    `error_message` TEXT DEFAULT NULL COMMENT '错误信息',
    `execution_time_ms` INT DEFAULT NULL COMMENT '执行时间 (毫秒)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `completed_at` TIMESTAMP NULL DEFAULT NULL COMMENT '完成时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`call_id`),
    KEY `idx_execution_id` (`execution_id`),
    KEY `idx_tool_name` (`tool_name`),
    KEY `idx_status` (`status`),
    KEY `idx_created_at` (`created_at`),
    CONSTRAINT `fk_toolcalls_execution` FOREIGN KEY (`execution_id`) REFERENCES `agent_executions` (`execution_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工具调用表';

-- ============================================
-- 8. 会话状态表 (conversation_states)
-- 存储会话的状态信息（用于复杂对话流程）
-- ============================================
CREATE TABLE IF NOT EXISTS `conversation_states` (
    `state_id` VARCHAR(36) NOT NULL COMMENT '状态ID (UUID)',
    `conversation_id` VARCHAR(36) NOT NULL COMMENT '会话ID',
    `state_key` VARCHAR(100) NOT NULL COMMENT '状态键',
    `state_value` JSON NOT NULL COMMENT '状态值 (JSON格式)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`state_id`),
    UNIQUE KEY `uk_conversation_key` (`conversation_id`, `state_key`),
    KEY `idx_conversation_id` (`conversation_id`),
    KEY `idx_state_key` (`state_key`),
    CONSTRAINT `fk_states_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话状态表';

-- ============================================
-- 9. 文件表 (files)
-- 存储用户上传的文件信息
-- ============================================
CREATE TABLE IF NOT EXISTS `files` (
    `file_id` VARCHAR(36) NOT NULL COMMENT '文件ID (UUID)',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `conversation_id` VARCHAR(36) DEFAULT NULL COMMENT '关联的会话ID',
    `original_filename` VARCHAR(255) NOT NULL COMMENT '原始文件名',
    `file_type` VARCHAR(50) NOT NULL COMMENT '文件类型 (pdf/docx/xlsx/txt等)',
    `file_size` BIGINT NOT NULL COMMENT '文件大小 (字节)',
    `storage_path` VARCHAR(500) NOT NULL COMMENT '文件存储路径',
    `processing_status` ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending' COMMENT '处理状态',
    `processed_at` TIMESTAMP NULL DEFAULT NULL COMMENT '处理完成时间',
    `error_message` TEXT DEFAULT NULL COMMENT '错误信息',
    `chunk_count` INT DEFAULT 0 COMMENT '文本块数量',
    `summary` TEXT DEFAULT NULL COMMENT '文件摘要',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式，知识库文档可包含knowledge_base_id/knowledge_base_name)',
    PRIMARY KEY (`file_id`),
    KEY `idx_user_id` (`user_id`),
    KEY `idx_conversation_id` (`conversation_id`),
    KEY `idx_file_type` (`file_type`),
    KEY `idx_processing_status` (`processing_status`),
    KEY `idx_created_at` (`created_at`),
    KEY `idx_user_conversation` (`user_id`, `conversation_id`),
    CONSTRAINT `fk_files_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
    CONSTRAINT `fk_files_conversation` FOREIGN KEY (`conversation_id`) REFERENCES `conversations` (`conversation_id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件表';

-- ============================================
-- 10. 文件分块表 (file_chunks)
-- 存储文件分块信息（用于向量检索）
-- ============================================
CREATE TABLE IF NOT EXISTS `file_chunks` (
    `chunk_id` VARCHAR(36) NOT NULL COMMENT '分块ID (UUID)',
    `file_id` VARCHAR(36) NOT NULL COMMENT '文件ID',
    `chunk_index` INT NOT NULL COMMENT '分块索引 (从0开始)',
    `content` TEXT NOT NULL COMMENT '分块内容',
    `page_number` INT DEFAULT NULL COMMENT '页码 (如果适用)',
    `start_char` INT DEFAULT NULL COMMENT '起始字符位置',
    `end_char` INT DEFAULT NULL COMMENT '结束字符位置',
    `token_count` INT DEFAULT NULL COMMENT 'Token数量',
    `vector_id` VARCHAR(100) DEFAULT NULL COMMENT '向量数据库中的ID',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`chunk_id`),
    KEY `idx_file_id` (`file_id`),
    KEY `idx_chunk_index` (`chunk_index`),
    KEY `idx_file_chunk` (`file_id`, `chunk_index`),
    KEY `idx_vector_id` (`vector_id`),
    CONSTRAINT `fk_chunks_file` FOREIGN KEY (`file_id`) REFERENCES `files` (`file_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件分块表';

-- ============================================
-- 11. 系统配置表 (system_configs)
-- 存储系统配置信息
-- ============================================
CREATE TABLE IF NOT EXISTS `system_configs` (
    `config_id` VARCHAR(36) NOT NULL COMMENT '配置ID (UUID)',
    `config_key` VARCHAR(100) NOT NULL COMMENT '配置键',
    `config_value` TEXT NOT NULL COMMENT '配置值',
    `config_type` VARCHAR(50) DEFAULT 'string' COMMENT '配置类型 (string/int/float/json/bool)',
    `description` VARCHAR(255) DEFAULT NULL COMMENT '配置描述',
    `is_active` TINYINT(1) DEFAULT 1 COMMENT '是否激活',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`config_id`),
    UNIQUE KEY `uk_config_key` (`config_key`),
    KEY `idx_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置表';

-- ============================================
-- 12. API调用日志表 (api_logs)
-- 存储API调用日志（可选，用于监控和审计）
-- ============================================
CREATE TABLE IF NOT EXISTS `api_logs` (
    `log_id` VARCHAR(36) NOT NULL COMMENT '日志ID (UUID)',
    `user_id` VARCHAR(36) DEFAULT NULL COMMENT '用户ID',
    `method` VARCHAR(10) NOT NULL COMMENT 'HTTP方法',
    `path` VARCHAR(255) NOT NULL COMMENT '请求路径',
    `status_code` INT NOT NULL COMMENT '响应状态码',
    `response_time_ms` INT DEFAULT NULL COMMENT '响应时间 (毫秒)',
    `ip_address` VARCHAR(45) DEFAULT NULL COMMENT 'IP地址',
    `user_agent` VARCHAR(255) DEFAULT NULL COMMENT 'User Agent',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `metadata` JSON DEFAULT NULL COMMENT '元数据 (JSON格式)',
    PRIMARY KEY (`log_id`),
    KEY `idx_user_id` (`user_id`),
    KEY `idx_method` (`method`),
    KEY `idx_status_code` (`status_code`),
    KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='API调用日志表';

-- ============================================
-- 创建触发器：自动更新会话的消息数量
-- ============================================
DELIMITER $$

CREATE TRIGGER `trg_messages_after_insert`
AFTER INSERT ON `messages`
FOR EACH ROW
BEGIN
    UPDATE `conversations`
    SET `message_count` = `message_count` + 1,
        `updated_at` = CURRENT_TIMESTAMP
    WHERE `conversation_id` = NEW.`conversation_id`;
END$$

CREATE TRIGGER `trg_messages_after_delete`
AFTER DELETE ON `messages`
FOR EACH ROW
BEGIN
    UPDATE `conversations`
    SET `message_count` = GREATEST(`message_count` - 1, 0),
        `updated_at` = CURRENT_TIMESTAMP
    WHERE `conversation_id` = OLD.`conversation_id`;
END$$

DELIMITER ;

-- ============================================
-- 插入默认系统配置
-- ============================================
INSERT INTO `system_configs` (`config_id`, `config_key`, `config_value`, `config_type`, `description`) VALUES
(UUID(), 'system.version', '1.0.0', 'string', '系统版本'),
(UUID(), 'system.maintenance_mode', 'false', 'bool', '维护模式'),
(UUID(), 'chat.max_history_messages', '10', 'int', '对话历史最大消息数'),
(UUID(), 'chat.max_message_length', '10000', 'int', '单条消息最大长度'),
(UUID(), 'file.max_upload_size', '10485760', 'int', '文件最大上传大小(字节)'),
(UUID(), 'file.allowed_types', '["pdf","docx","xlsx","txt","md"]', 'json', '允许的文件类型');

-- ============================================
-- 恢复外键检查
-- ============================================
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================
-- 数据库初始化完成
-- ============================================

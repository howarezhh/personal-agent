-- 本文件使用 UTF-8 编码，请使用支持 UTF-8 的编辑器查看和执行。
-- 企业级多Agent知识库助手 - 数据库初始化脚本
-- 数据库: MySQL 5.7+
-- 字符集: utf8mb4
-- 排序规则: utf8mb4_unicode_ci

-- ============================================
-- 1. 用户表 (users)
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(36) PRIMARY KEY COMMENT '用户ID (UUID)',
    username VARCHAR(50) NOT NULL UNIQUE COMMENT '用户名',
    email VARCHAR(100) NOT NULL UNIQUE COMMENT '邮箱',
    password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
    full_name VARCHAR(100) COMMENT '全名',
    avatar_url VARCHAR(500) COMMENT '头像URL',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    is_admin BOOLEAN DEFAULT FALSE COMMENT '是否管理员',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    last_login_at TIMESTAMP NULL COMMENT '最后登录时间',
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_is_active (is_active),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ============================================
-- 2. 会话表 (conversations)
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id VARCHAR(36) PRIMARY KEY COMMENT '会话ID (UUID)',
    user_id VARCHAR(36) NOT NULL COMMENT '用户ID',
    title VARCHAR(200) DEFAULT '新对话' COMMENT '会话标题',
    description TEXT COMMENT '会话描述',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    message_count INT DEFAULT 0 COMMENT '消息数量',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_user_id (user_id),
    INDEX idx_is_active (is_active),
    INDEX idx_created_at (created_at),
    INDEX idx_updated_at (updated_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话表';

-- ============================================
-- 3. 知识库表 (knowledge_bases)
-- ============================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    knowledge_base_id VARCHAR(36) PRIMARY KEY COMMENT '知识库ID (UUID)',
    user_id VARCHAR(36) NOT NULL COMMENT '用户ID',
    name VARCHAR(100) NOT NULL COMMENT '知识库名称',
    description TEXT COMMENT '知识库描述',
    is_default BOOLEAN DEFAULT FALSE COMMENT '是否默认知识库',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_kb_user_active_created (user_id, is_active, created_at),
    INDEX idx_kb_user_default (user_id, is_default),
    INDEX idx_kb_user_name (user_id, name),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- ============================================
-- 4. 消息表 (messages)
-- ============================================
CREATE TABLE IF NOT EXISTS messages (
    message_id VARCHAR(36) PRIMARY KEY COMMENT '消息ID (UUID)',
    conversation_id VARCHAR(36) NOT NULL COMMENT '会话ID',
    message_type ENUM('user', 'assistant', 'system') NOT NULL COMMENT '消息类型',
    content TEXT NOT NULL COMMENT '消息内容',
    sequence_number INT NOT NULL COMMENT '消息序号',
    parent_message_id VARCHAR(36) COMMENT '父消息ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_message_type (message_type),
    INDEX idx_sequence_number (sequence_number),
    INDEX idx_created_at (created_at),
    UNIQUE KEY uk_conversation_sequence (conversation_id, sequence_number),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_message_id) REFERENCES messages(message_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='消息表';

-- ============================================
-- 5. 智能体执行记录表 (agent_executions)
-- ============================================
CREATE TABLE IF NOT EXISTS agent_executions (
    execution_id VARCHAR(36) PRIMARY KEY COMMENT '执行ID (UUID)',
    conversation_id VARCHAR(36) NULL COMMENT '会话ID (可为空，直接工具调用时为NULL)',
    message_id VARCHAR(36) COMMENT '消息ID',
    agent_name VARCHAR(100) NOT NULL COMMENT '智能体名称',
    agent_type ENUM('router', 'retrieval', 'generation', 'tool', 'file_processor') NOT NULL COMMENT '智能体类型',
    input_data JSON COMMENT '输入数据',
    output_data JSON COMMENT '输出数据',
    status ENUM('success', 'failed', 'partial', 'running') DEFAULT 'running' COMMENT '执行状态',
    error_message TEXT COMMENT '错误信息',
    execution_time_ms INT COMMENT '执行时间(毫秒)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    completed_at TIMESTAMP NULL COMMENT '完成时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_message_id (message_id),
    INDEX idx_agent_name (agent_name),
    INDEX idx_agent_type (agent_type),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体执行记录表';

-- ============================================
-- 6. 检索结果表 (retrieval_results)
-- ============================================
CREATE TABLE IF NOT EXISTS retrieval_results (
    result_id VARCHAR(36) PRIMARY KEY COMMENT '结果ID (UUID)',
    execution_id VARCHAR(36) NOT NULL COMMENT '执行ID',
    source_type VARCHAR(50) COMMENT '来源类型',
    source_id VARCHAR(100) COMMENT '来源ID',
    content TEXT NOT NULL COMMENT '检索内容',
    relevance_score FLOAT COMMENT '相关度分数',
    rank_position INT COMMENT '排序位置',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_execution_id (execution_id),
    INDEX idx_source_type (source_type),
    INDEX idx_relevance_score (relevance_score),
    INDEX idx_rank_position (rank_position),
    FOREIGN KEY (execution_id) REFERENCES agent_executions(execution_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='检索结果表';

-- ============================================
-- 7. 工具调用表 (tool_calls)
-- ============================================
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id VARCHAR(36) PRIMARY KEY COMMENT '调用ID (UUID)',
    execution_id VARCHAR(36) NOT NULL COMMENT '执行ID',
    tool_name VARCHAR(100) NOT NULL COMMENT '工具名称',
    tool_input JSON COMMENT '工具输入',
    tool_output JSON COMMENT '工具输出',
    status ENUM('success', 'failed', 'running') DEFAULT 'running' COMMENT '调用状态',
    error_message TEXT COMMENT '错误信息',
    execution_time_ms INT COMMENT '执行时间(毫秒)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    completed_at TIMESTAMP NULL COMMENT '完成时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_execution_id (execution_id),
    INDEX idx_tool_name (tool_name),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (execution_id) REFERENCES agent_executions(execution_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工具调用表';

-- ============================================
-- 8. 会话状态表 (conversation_states)
-- ============================================
CREATE TABLE IF NOT EXISTS conversation_states (
    state_id VARCHAR(36) PRIMARY KEY COMMENT '状态ID (UUID)',
    conversation_id VARCHAR(36) NOT NULL COMMENT '会话ID',
    state_data JSON NOT NULL COMMENT '状态数据',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_updated_at (updated_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='会话状态表';

-- ============================================
-- 9. 文件表 (files)
-- ============================================
CREATE TABLE IF NOT EXISTS files (
    file_id VARCHAR(36) PRIMARY KEY COMMENT '文件ID (UUID)',
    user_id VARCHAR(36) NOT NULL COMMENT '用户ID',
    conversation_id VARCHAR(36) COMMENT '会话ID',
    original_filename VARCHAR(255) NOT NULL COMMENT '原始文件名',
    file_type VARCHAR(50) NOT NULL COMMENT '文件类型',
    file_size BIGINT NOT NULL COMMENT '文件大小(字节)',
    storage_path VARCHAR(500) NOT NULL COMMENT '文件存储路径',
    processing_status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending' COMMENT '处理状态',
    processed_at TIMESTAMP NULL COMMENT '处理完成时间',
    error_message TEXT COMMENT '错误信息',
    chunk_count INT DEFAULT 0 COMMENT '文本块数量',
    summary TEXT COMMENT '文件摘要',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    metadata JSON COMMENT '元数据（知识库文档可包含knowledge_base_id/knowledge_base_name）',
    INDEX idx_user_id (user_id),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_file_type (file_type),
    INDEX idx_processing_status (processing_status),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件表';

-- ============================================
-- 10. 文件分块表 (file_chunks)
-- ============================================
CREATE TABLE IF NOT EXISTS file_chunks (
    chunk_id VARCHAR(36) PRIMARY KEY COMMENT '分块ID (UUID)',
    file_id VARCHAR(36) NOT NULL COMMENT '文件ID',
    chunk_index INT NOT NULL COMMENT '分块索引',
    content TEXT NOT NULL COMMENT '分块内容',
    page_number INT COMMENT '页码',
    start_char INT COMMENT '起始字符位置',
    end_char INT COMMENT '结束字符位置',
    token_count INT COMMENT 'Token数量',
    vector_id VARCHAR(100) COMMENT '向量ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    metadata JSON COMMENT '元数据',
    INDEX idx_file_id (file_id),
    INDEX idx_chunk_index (chunk_index),
    INDEX idx_vector_id (vector_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文件分块表';

-- ============================================
-- 11. 系统配置表 (system_configs)
-- ============================================
CREATE TABLE IF NOT EXISTS system_configs (
    config_id VARCHAR(36) PRIMARY KEY COMMENT '配置ID (UUID)',
    config_key VARCHAR(100) NOT NULL UNIQUE COMMENT '配置键',
    config_value TEXT NOT NULL COMMENT '配置值',
    config_type VARCHAR(50) DEFAULT 'string' COMMENT '配置类型',
    description TEXT COMMENT '配置描述',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_config_key (config_key),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置表';

-- ============================================
-- 12. 审计日志表 (audit_logs)
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '日志ID',
    user_id VARCHAR(36) COMMENT '用户ID',
    action VARCHAR(100) NOT NULL COMMENT '操作类型',
    resource_type VARCHAR(50) COMMENT '资源类型',
    resource_id VARCHAR(36) COMMENT '资源ID',
    details JSON COMMENT '详细信息',
    ip_address VARCHAR(45) COMMENT 'IP地址',
    user_agent TEXT COMMENT '用户代理',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_user_id (user_id),
    INDEX idx_action (action),
    INDEX idx_resource_type (resource_type),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';

-- ============================================
-- 初始化数据
-- ============================================

-- 插入默认系统配置
INSERT INTO system_configs (config_id, config_key, config_value, config_type, description) VALUES
(UUID(), 'system.version', '1.0.0', 'string', '系统版本'),
(UUID(), 'system.maintenance_mode', 'false', 'boolean', '维护模式'),
(UUID(), 'system.max_conversation_history', '50', 'integer', '最大对话历史记录数'),
(UUID(), 'system.max_file_size_mb', '10', 'integer', '最大文件大小(MB)'),
(UUID(), 'system.allowed_file_types', 'pdf,docx,xlsx,txt,md', 'string', '允许的文件类型')
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;

-- ============================================
-- 创建视图
-- ============================================

-- 用户会话摘要视图
CREATE OR REPLACE VIEW v_user_conversation_summary AS
SELECT
    c.conversation_id,
    c.user_id,
    c.title,
    c.message_count,
    c.created_at,
    c.updated_at,
    u.username,
    u.email,
    (SELECT content FROM messages WHERE conversation_id = c.conversation_id AND message_type = 'user' ORDER BY sequence_number DESC LIMIT 1) as last_user_message,
    (SELECT created_at FROM messages WHERE conversation_id = c.conversation_id ORDER BY sequence_number DESC LIMIT 1) as last_message_time
FROM conversations c
JOIN users u ON c.user_id = u.user_id
WHERE c.is_active = TRUE;

-- 智能体执行统计视图
CREATE OR REPLACE VIEW v_agent_execution_stats AS
SELECT
    conversation_id,
    agent_type,
    COUNT(*) as total_executions,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
    AVG(execution_time_ms) as avg_execution_time_ms,
    MAX(execution_time_ms) as max_execution_time_ms,
    MIN(execution_time_ms) as min_execution_time_ms
FROM agent_executions
GROUP BY conversation_id, agent_type;

-- ============================================
-- 完成
-- ============================================

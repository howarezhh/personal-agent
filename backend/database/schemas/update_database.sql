-- ============================================
-- 数据库更新脚本
-- 用于在已有数据库基础上添加新表
-- 执行前请确保已经运行过 create_tables.sql
-- 创建时间: 2024-01-15
-- ============================================

-- 设置字符集
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================
-- 第一部分：内容生成功能表
-- ============================================

-- 1. 内容生成记录表
CREATE TABLE IF NOT EXISTS `content_generations` (
    `id` VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `conversation_id` VARCHAR(36) COMMENT '会话ID（可选）',
    `content_type` VARCHAR(50) NOT NULL COMMENT '内容类型：novel/script/optimization',
    `action` VARCHAR(50) NOT NULL COMMENT '操作类型：outline/chapter/scene/polish等',
    `input_params` JSON NOT NULL COMMENT '输入参数（JSON格式）',
    `output_content` LONGTEXT COMMENT '输出内容',
    `status` VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/completed/failed',
    `error_message` TEXT COMMENT '错误信息',
    `execution_time` INT COMMENT '执行时间（毫秒）',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_conversation_id` (`conversation_id`),
    INDEX `idx_content_type` (`content_type`),
    INDEX `idx_status` (`status`),
    INDEX `idx_created_at` (`created_at`),
    CONSTRAINT `fk_content_gen_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容生成记录表';

-- 2. 内容项目表
CREATE TABLE IF NOT EXISTS `content_projects` (
    `id` VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `project_name` VARCHAR(255) NOT NULL COMMENT '项目名称',
    `project_type` VARCHAR(50) NOT NULL COMMENT '项目类型：novel/script',
    `genre` VARCHAR(50) COMMENT '类型/风格',
    `metadata` JSON COMMENT '项目元数据（包含大纲、角色、设定等）',
    `status` VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT '状态：draft/in_progress/completed/archived',
    `word_count` INT DEFAULT 0 COMMENT '总字数',
    `chapter_count` INT DEFAULT 0 COMMENT '章节数/场次数',
    `last_edited_at` TIMESTAMP COMMENT '最后编辑时间',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_project_type` (`project_type`),
    INDEX `idx_status` (`status`),
    INDEX `idx_created_at` (`created_at`),
    CONSTRAINT `fk_content_proj_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容项目表';

-- 3. 内容章节表
CREATE TABLE IF NOT EXISTS `content_chapters` (
    `id` VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    `project_id` VARCHAR(36) NOT NULL COMMENT '项目ID',
    `chapter_number` INT NOT NULL COMMENT '章节编号/场次编号',
    `chapter_title` VARCHAR(255) COMMENT '章节标题/场景标题',
    `content` LONGTEXT COMMENT '章节内容',
    `word_count` INT DEFAULT 0 COMMENT '字数',
    `status` VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT '状态：draft/completed',
    `notes` TEXT COMMENT '备注',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_project_id` (`project_id`),
    INDEX `idx_chapter_number` (`chapter_number`),
    INDEX `idx_status` (`status`),
    UNIQUE KEY `uk_project_chapter` (`project_id`, `chapter_number`),
    CONSTRAINT `fk_content_chap_proj` FOREIGN KEY (`project_id`) REFERENCES `content_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容章节表';

-- 4. 内容角色表
CREATE TABLE IF NOT EXISTS `content_characters` (
    `id` VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    `project_id` VARCHAR(36) NOT NULL COMMENT '项目ID',
    `character_name` VARCHAR(255) NOT NULL COMMENT '角色名称',
    `character_data` JSON NOT NULL COMMENT '角色数据（包含年龄、性格、背景等）',
    `avatar_url` VARCHAR(500) COMMENT '角色头像URL',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_project_id` (`project_id`),
    CONSTRAINT `fk_content_char_proj` FOREIGN KEY (`project_id`) REFERENCES `content_projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容角色表';

-- ============================================
-- 第二部分：MCP服务管理表
-- ============================================

-- 5. MCP服务配置表
CREATE TABLE IF NOT EXISTS `mcp_services` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MCP服务ID',
    `name` VARCHAR(100) NOT NULL UNIQUE COMMENT 'MCP服务名称',
    `description` TEXT COMMENT 'MCP服务描述',
    `category` VARCHAR(50) DEFAULT 'mcp' COMMENT 'MCP分类',
    `version` VARCHAR(20) DEFAULT '1.0.0' COMMENT '版本号',
    `api_endpoint` VARCHAR(500) COMMENT 'API端点',
    `requires_api_key` BOOLEAN DEFAULT FALSE COMMENT '是否需要API密钥',
    `is_enabled` BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    `timeout` INT DEFAULT 30 COMMENT '超时时间（秒）',
    `parameters` JSON COMMENT '参数定义（JSON格式）',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_name` (`name`),
    INDEX `idx_category` (`category`),
    INDEX `idx_enabled` (`is_enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP服务配置表';

-- 6. MCP调用记录表
CREATE TABLE IF NOT EXISTS `mcp_call_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '调用记录ID',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `mcp_name` VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    `parameters` JSON COMMENT '调用参数',
    `result` JSON COMMENT '调用结果',
    `success` BOOLEAN DEFAULT FALSE COMMENT '是否成功',
    `error_message` TEXT COMMENT '错误信息',
    `execution_time` INT COMMENT '执行时间（毫秒）',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_mcp_name` (`mcp_name`),
    INDEX `idx_created_at` (`created_at`),
    INDEX `idx_success` (`success`),
    CONSTRAINT `fk_mcp_log_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP调用记录表';

-- 7. MCP用户配置表
CREATE TABLE IF NOT EXISTS `mcp_user_configs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '配置ID',
    `user_id` VARCHAR(36) NOT NULL COMMENT '用户ID',
    `mcp_name` VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    `api_key` VARCHAR(500) COMMENT 'API密钥（加密存储）',
    `custom_config` JSON COMMENT '自定义配置',
    `is_active` BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY `uk_user_mcp` (`user_id`, `mcp_name`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_mcp_name` (`mcp_name`),
    CONSTRAINT `fk_mcp_config_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP用户配置表';

-- 8. MCP使用统计表
CREATE TABLE IF NOT EXISTS `mcp_usage_stats` (
    `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '统计ID',
    `mcp_name` VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    `user_id` VARCHAR(36) COMMENT '用户ID（NULL表示全局统计）',
    `date` DATE NOT NULL COMMENT '统计日期',
    `total_calls` INT DEFAULT 0 COMMENT '总调用次数',
    `success_calls` INT DEFAULT 0 COMMENT '成功调用次数',
    `failed_calls` INT DEFAULT 0 COMMENT '失败调用次数',
    `avg_execution_time` INT COMMENT '平均执行时间（毫秒）',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY `uk_mcp_user_date` (`mcp_name`, `user_id`, `date`),
    INDEX `idx_mcp_name` (`mcp_name`),
    INDEX `idx_user_id` (`user_id`),
    INDEX `idx_date` (`date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP使用统计表';

-- ============================================
-- 插入默认MCP服务配置
-- ============================================
INSERT IGNORE INTO `mcp_services` (`name`, `description`, `category`, `api_endpoint`, `requires_api_key`, `parameters`) VALUES
('weather_mcp', '查询天气信息，支持当前天气和未来7天预报', 'mcp', 'https://api.open-meteo.com/v1/forecast', FALSE,
'{"type": "object", "properties": {"city": {"type": "string", "description": "城市名称"}, "forecast_days": {"type": "number", "description": "预报天数（1-7天）"}}, "required": ["city"]}'),

('news_mcp', '查询最新新闻，支持关键词搜索和分类查询', 'mcp', 'https://newsapi.org/v2/top-headlines', TRUE,
'{"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "category": {"type": "string", "description": "新闻类别"}, "country": {"type": "string", "description": "国家代码"}}, "required": []}'),

('wikipedia_mcp', '搜索维基百科，获取百科知识', 'mcp', 'https://zh.wikipedia.org/w/api.php', FALSE,
'{"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}, "language": {"type": "string", "description": "语言（zh/en）"}, "limit": {"type": "number", "description": "返回结果数量"}}, "required": ["query"]}'),

('exchange_rate_mcp', '查询实时汇率和货币转换', 'mcp', 'https://open.er-api.com/v6/latest', FALSE,
'{"type": "object", "properties": {"from_currency": {"type": "string", "description": "源货币代码"}, "to_currency": {"type": "string", "description": "目标货币代码"}, "amount": {"type": "number", "description": "转换金额"}}, "required": ["from_currency"]}'),

('ip_lookup_mcp', '查询IP地址的地理位置和ISP信息', 'mcp', 'http://ip-api.com/json', FALSE,
'{"type": "object", "properties": {"ip_address": {"type": "string", "description": "IP地址"}, "language": {"type": "string", "description": "返回语言"}}, "required": []}');

-- ============================================
-- 创建MCP统计触发器
-- ============================================
DELIMITER $$

DROP TRIGGER IF EXISTS `trg_mcp_call_after_insert`$$

CREATE TRIGGER `trg_mcp_call_after_insert`
AFTER INSERT ON `mcp_call_logs`
FOR EACH ROW
BEGIN
    DECLARE call_date DATE;
    SET call_date = DATE(NEW.created_at);

    -- 更新用户级别统计
    INSERT INTO `mcp_usage_stats` (`mcp_name`, `user_id`, `date`, `total_calls`, `success_calls`, `failed_calls`, `avg_execution_time`)
    VALUES (NEW.mcp_name, NEW.user_id, call_date, 1,
            IF(NEW.success, 1, 0),
            IF(NEW.success, 0, 1),
            NEW.execution_time)
    ON DUPLICATE KEY UPDATE
        `total_calls` = `total_calls` + 1,
        `success_calls` = `success_calls` + IF(NEW.success, 1, 0),
        `failed_calls` = `failed_calls` + IF(NEW.success, 0, 1),
        `avg_execution_time` = (`avg_execution_time` * `total_calls` + NEW.execution_time) / (`total_calls` + 1);

    -- 更新全局统计
    INSERT INTO `mcp_usage_stats` (`mcp_name`, `user_id`, `date`, `total_calls`, `success_calls`, `failed_calls`, `avg_execution_time`)
    VALUES (NEW.mcp_name, NULL, call_date, 1,
            IF(NEW.success, 1, 0),
            IF(NEW.success, 0, 1),
            NEW.execution_time)
    ON DUPLICATE KEY UPDATE
        `total_calls` = `total_calls` + 1,
        `success_calls` = `success_calls` + IF(NEW.success, 1, 0),
        `failed_calls` = `failed_calls` + IF(NEW.success, 0, 1),
        `avg_execution_time` = (`avg_execution_time` * `total_calls` + NEW.execution_time) / (`total_calls` + 1);
END$$

DELIMITER ;

-- ============================================
-- 恢复外键检查
-- ============================================
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================
-- 数据库更新完成
-- ============================================
-- 执行结果说明：
-- 1. 已创建 4 个内容生成相关表
-- 2. 已创建 4 个MCP服务管理表
-- 3. 已插入默认MCP服务配置
-- 4. 已创建MCP统计触发器
--
-- 注意事项：
-- - 使用 CREATE TABLE IF NOT EXISTS 确保不会覆盖已有表
-- - 使用 INSERT IGNORE 确保不会重复插入默认数据
-- - 所有外键约束已正确设置
-- - 所有索引已创建以优化查询性能
-- ============================================

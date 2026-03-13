-- MCP服务管理数据库表
-- 用于记录MCP服务的使用情况和配置

-- 1. MCP服务配置表
CREATE TABLE IF NOT EXISTS mcp_services (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT 'MCP服务ID',
    name VARCHAR(100) NOT NULL UNIQUE COMMENT 'MCP服务名称',
    description TEXT COMMENT 'MCP服务描述',
    category VARCHAR(50) DEFAULT 'mcp' COMMENT 'MCP分类',
    version VARCHAR(20) DEFAULT '1.0.0' COMMENT '版本号',
    api_endpoint VARCHAR(500) COMMENT 'API端点',
    requires_api_key BOOLEAN DEFAULT FALSE COMMENT '是否需要API密钥',
    is_enabled BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    timeout INT DEFAULT 30 COMMENT '超时时间（秒）',
    parameters JSON COMMENT '参数定义（JSON格式）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_name (name),
    INDEX idx_category (category),
    INDEX idx_enabled (is_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP服务配置表';

-- 2. MCP调用记录表
CREATE TABLE IF NOT EXISTS mcp_call_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '调用记录ID',
    user_id INT NOT NULL COMMENT '用户ID',
    mcp_name VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    parameters JSON COMMENT '调用参数',
    result JSON COMMENT '调用结果',
    success BOOLEAN DEFAULT FALSE COMMENT '是否成功',
    error_message TEXT COMMENT '错误信息',
    execution_time INT COMMENT '执行时间（毫秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '调用时间',
    INDEX idx_user_id (user_id),
    INDEX idx_mcp_name (mcp_name),
    INDEX idx_created_at (created_at),
    INDEX idx_success (success),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP调用记录表';

-- 3. MCP用户配置表（用于存储用户的API密钥等配置）
CREATE TABLE IF NOT EXISTS mcp_user_configs (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '配置ID',
    user_id INT NOT NULL COMMENT '用户ID',
    mcp_name VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    api_key VARCHAR(500) COMMENT 'API密钥（加密存储）',
    custom_config JSON COMMENT '自定义配置',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否激活',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_user_mcp (user_id, mcp_name),
    INDEX idx_user_id (user_id),
    INDEX idx_mcp_name (mcp_name),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP用户配置表';

-- 4. MCP使用统计表
CREATE TABLE IF NOT EXISTS mcp_usage_stats (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '统计ID',
    mcp_name VARCHAR(100) NOT NULL COMMENT 'MCP服务名称',
    user_id INT COMMENT '用户ID（NULL表示全局统计）',
    date DATE NOT NULL COMMENT '统计日期',
    total_calls INT DEFAULT 0 COMMENT '总调用次数',
    success_calls INT DEFAULT 0 COMMENT '成功调用次数',
    failed_calls INT DEFAULT 0 COMMENT '失败调用次数',
    avg_execution_time INT COMMENT '平均执行时间（毫秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_mcp_user_date (mcp_name, user_id, date),
    INDEX idx_mcp_name (mcp_name),
    INDEX idx_user_id (user_id),
    INDEX idx_date (date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MCP使用统计表';

-- 插入默认的MCP服务配置
INSERT INTO mcp_services (name, description, category, api_endpoint, requires_api_key, parameters) VALUES
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

-- 创建触发器：自动更新MCP使用统计
DELIMITER //

CREATE TRIGGER after_mcp_call_insert
AFTER INSERT ON mcp_call_logs
FOR EACH ROW
BEGIN
    DECLARE call_date DATE;
    SET call_date = DATE(NEW.created_at);

    -- 更新用户级别统计
    INSERT INTO mcp_usage_stats (mcp_name, user_id, date, total_calls, success_calls, failed_calls, avg_execution_time)
    VALUES (NEW.mcp_name, NEW.user_id, call_date, 1,
            IF(NEW.success, 1, 0),
            IF(NEW.success, 0, 1),
            NEW.execution_time)
    ON DUPLICATE KEY UPDATE
        total_calls = total_calls + 1,
        success_calls = success_calls + IF(NEW.success, 1, 0),
        failed_calls = failed_calls + IF(NEW.success, 0, 1),
        avg_execution_time = (avg_execution_time * total_calls + NEW.execution_time) / (total_calls + 1);

    -- 更新全局统计
    INSERT INTO mcp_usage_stats (mcp_name, user_id, date, total_calls, success_calls, failed_calls, avg_execution_time)
    VALUES (NEW.mcp_name, NULL, call_date, 1,
            IF(NEW.success, 1, 0),
            IF(NEW.success, 0, 1),
            NEW.execution_time)
    ON DUPLICATE KEY UPDATE
        total_calls = total_calls + 1,
        success_calls = success_calls + IF(NEW.success, 1, 0),
        failed_calls = failed_calls + IF(NEW.success, 0, 1),
        avg_execution_time = (avg_execution_time * total_calls + NEW.execution_time) / (total_calls + 1);
END//

DELIMITER ;

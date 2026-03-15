-- 本文件使用 UTF-8 编码，请使用支持 UTF-8 的编辑器查看和执行。
-- 内容生成功能数据库扩展
-- 创建内容生成记录表和内容项目表

-- ==================== 内容生成记录表 ====================

CREATE TABLE IF NOT EXISTS content_generations (
    id VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    user_id VARCHAR(36) NOT NULL COMMENT '用户ID',
    conversation_id VARCHAR(36) COMMENT '会话ID（可选）',
    content_type VARCHAR(50) NOT NULL COMMENT '内容类型：novel/script/optimization',
    action VARCHAR(50) NOT NULL COMMENT '操作类型：outline/chapter/scene/polish等',
    input_params JSON NOT NULL COMMENT '输入参数（JSON格式）',
    output_content LONGTEXT COMMENT '输出内容',
    status VARCHAR(20) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/completed/failed',
    error_message TEXT COMMENT '错误信息',
    execution_time INT COMMENT '执行时间（毫秒）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user_id (user_id),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_content_type (content_type),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容生成记录表';


-- ==================== 内容项目表 ====================

CREATE TABLE IF NOT EXISTS content_projects (
    id VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    user_id VARCHAR(36) NOT NULL COMMENT '用户ID',
    project_name VARCHAR(255) NOT NULL COMMENT '项目名称',
    project_type VARCHAR(50) NOT NULL COMMENT '项目类型：novel/script',
    genre VARCHAR(50) COMMENT '类型/风格',
    metadata JSON COMMENT '项目元数据（包含大纲、角色、设定等）',
    status VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT '状态：draft/in_progress/completed/archived',
    word_count INT DEFAULT 0 COMMENT '总字数',
    chapter_count INT DEFAULT 0 COMMENT '章节数/场次数',
    last_edited_at TIMESTAMP COMMENT '最后编辑时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user_id (user_id),
    INDEX idx_project_type (project_type),
    INDEX idx_status (status),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容项目表';


-- ==================== 内容章节表 ====================

CREATE TABLE IF NOT EXISTS content_chapters (
    id VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    project_id VARCHAR(36) NOT NULL COMMENT '项目ID',
    chapter_number INT NOT NULL COMMENT '章节编号/场次编号',
    chapter_title VARCHAR(255) COMMENT '章节标题/场景标题',
    content LONGTEXT COMMENT '章节内容',
    word_count INT DEFAULT 0 COMMENT '字数',
    status VARCHAR(20) NOT NULL DEFAULT 'draft' COMMENT '状态：draft/completed',
    notes TEXT COMMENT '备注',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_project_id (project_id),
    INDEX idx_chapter_number (chapter_number),
    INDEX idx_status (status),
    UNIQUE KEY uk_project_chapter (project_id, chapter_number),
    FOREIGN KEY (project_id) REFERENCES content_projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容章节表';


-- ==================== 内容角色表 ====================

CREATE TABLE IF NOT EXISTS content_characters (
    id VARCHAR(36) PRIMARY KEY COMMENT '主键ID',
    project_id VARCHAR(36) NOT NULL COMMENT '项目ID',
    character_name VARCHAR(255) NOT NULL COMMENT '角色名称',
    character_data JSON NOT NULL COMMENT '角色数据（包含年龄、性格、背景等）',
    avatar_url VARCHAR(500) COMMENT '角色头像URL',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_project_id (project_id),
    FOREIGN KEY (project_id) REFERENCES content_projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内容角色表';


-- ==================== 示例数据插入 ====================

-- 注意：以下示例数据仅用于测试，生产环境请删除

-- 示例：内容生成记录
-- INSERT INTO content_generations (id, user_id, content_type, action, input_params, output_content, status)
-- VALUES (
--     UUID(),
--     'user_id_here',
--     'novel',
--     'outline',
--     '{"title": "修仙之路", "genre": "xianxia", "theme": "一个普通少年的修仙历程"}',
--     '{"background": "修仙世界", "main_characters": [...]}',
--     'completed'
-- );

-- 示例：内容项目
-- INSERT INTO content_projects (id, user_id, project_name, project_type, genre, status)
-- VALUES (
--     UUID(),
--     'user_id_here',
--     '修仙之路',
--     'novel',
--     'xianxia',
--     'in_progress'
-- );


-- ==================== 查询示例 ====================

-- 查询用户的所有内容生成记录
-- SELECT * FROM content_generations WHERE user_id = 'user_id_here' ORDER BY created_at DESC;

-- 查询用户的所有项目
-- SELECT * FROM content_projects WHERE user_id = 'user_id_here' ORDER BY last_edited_at DESC;

-- 查询项目的所有章节
-- SELECT * FROM content_chapters WHERE project_id = 'project_id_here' ORDER BY chapter_number ASC;

-- 查询项目的所有角色
-- SELECT * FROM content_characters WHERE project_id = 'project_id_here';

-- 统计用户的内容生成次数
-- SELECT content_type, action, COUNT(*) as count
-- FROM content_generations
-- WHERE user_id = 'user_id_here' AND status = 'completed'
-- GROUP BY content_type, action;

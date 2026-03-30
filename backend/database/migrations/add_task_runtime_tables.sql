-- 任务运行时持久化表
-- 用于保存任务执行记录、检查点与标准产物索引

CREATE TABLE IF NOT EXISTS task_runtime_executions (
    task_id VARCHAR(64) PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    execution_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    conversation_id VARCHAR(64) NOT NULL,
    message_id VARCHAR(64) NULL,
    user_input TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    current_plan_id VARCHAR(64) NULL,
    current_step_id VARCHAR(64) NULL,
    checkpoint_id VARCHAR(64) NULL,
    goal_json LONGTEXT NOT NULL,
    current_plan_json LONGTEXT NULL,
    state_json LONGTEXT NOT NULL,
    termination_json LONGTEXT NULL,
    evaluation_report_json LONGTEXT NULL,
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    INDEX idx_task_runtime_exec_user_updated (user_id, updated_at),
    INDEX idx_task_runtime_exec_conversation (conversation_id),
    INDEX idx_task_runtime_exec_execution (execution_id)
);

CREATE TABLE IF NOT EXISTS task_runtime_checkpoints (
    checkpoint_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    execution_id VARCHAR(64) NULL,
    status VARCHAR(32) NOT NULL,
    iteration_count INT NOT NULL DEFAULT 0,
    completed_step_ids_json LONGTEXT NOT NULL,
    latest_plan_id VARCHAR(64) NULL,
    latest_step_id VARCHAR(64) NULL,
    checkpoint_reason VARCHAR(255) NOT NULL,
    state_json LONGTEXT NOT NULL,
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    INDEX idx_task_runtime_checkpoint_task_created (task_id, created_at),
    CONSTRAINT fk_task_runtime_checkpoint_task
        FOREIGN KEY (task_id) REFERENCES task_runtime_executions(task_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_runtime_artifacts (
    artifact_id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    artifact_type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content_json LONGTEXT NULL,
    source_plan_id VARCHAR(64) NULL,
    source_step_id VARCHAR(64) NULL,
    metadata_json LONGTEXT NOT NULL,
    created_at VARCHAR(64) NOT NULL,
    INDEX idx_task_runtime_artifact_task_created (task_id, created_at),
    CONSTRAINT fk_task_runtime_artifact_task
        FOREIGN KEY (task_id) REFERENCES task_runtime_executions(task_id)
        ON DELETE CASCADE
);

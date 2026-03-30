"""配置管理模块。

该模块负责：
1. 在导入时确保环境变量已优先加载；
2. 按约定目录读取基础配置、环境覆盖配置与配置 Schema；
3. 对外提供统一的配置查询、环境变量覆盖与常用配置访问能力；
4. 通过单例函数复用同一个配置管理器实例，避免重复加载配置文件。
"""

from backend.core.env_loader import load_environment

# 在配置模块初始化前优先加载环境变量，确保后续读取配置时可以正确解析 *_env 映射项。
load_environment()

import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml


# 当前模块使用的日志记录器。
logger = logging.getLogger(__name__)


# 基础配置文件映射表。
# key 表示内部配置命名空间，value 表示 config/base 下对应的 YAML 文件名。
BASE_CONFIG_FILES = {
    "model": "model.yaml",
    "database": "database.yaml",
    "agent": "agent.yaml",
    "business": "business.yaml",
    "tools": "tools.yaml",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并两个字典。

    该函数用于实现“基础配置 + 环境配置覆盖”的能力：
    - 当同名键对应的值都是字典时，继续递归合并；
    - 否则直接使用覆盖值替换基础值。

    Args:
        base: 基础配置字典。
        override: 需要覆盖到基础配置上的字典。

    Returns:
        合并后的新字典，不会原地修改传入参数。
    """
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    """统一配置管理器。

    该类负责集中读取项目中的配置文件，并向业务层提供稳定的访问入口。
    配置加载顺序遵循以下思路：
    1. 先读取 `config/base/` 下的基础配置；
    2. 再读取 `config/env/{env}.yaml` 作为环境覆盖；
    3. 最后在读取具体配置时，允许通过环境变量进一步覆盖敏感项。
    """

    def __init__(self, config_dir: str | None = None):
        """初始化配置管理器并加载全部配置。

        Args:
            config_dir: 配置目录路径。若为空，则自动从项目根目录下定位 `config/`。
        """
        if config_dir is None:
            from backend.utils.path_utils import find_project_root

            project_root = find_project_root(Path(__file__).parent)
            config_dir = project_root / "config"

        # 保存配置根目录，后续所有配置文件都相对该目录解析。
        self.config_dir = Path(config_dir)
        # 用于缓存已加载的配置内容，避免重复读盘。
        self._configs: dict[str, Any] = {}
        self._load_all_configs()

    def _load_all_configs(self):
        """加载全部配置文件。

        该方法会：
        - 识别当前运行环境；
        - 读取基础配置；
        - 读取环境覆盖配置；
        - 将配置 Schema 一并加载到缓存中。
        """
        # 允许 APP_ENV 覆盖 ENV；若都不存在，则默认使用 development。
        env_name = os.getenv("APP_ENV", os.getenv("ENV", "development"))

        env_path = self.config_dir / "env" / f"{env_name}.yaml"
        env_override = self._load_yaml(env_path) if env_path.exists() else {}

        for name, file_name in BASE_CONFIG_FILES.items():
            base_path = self.config_dir / "base" / file_name
            if not base_path.exists():
                logger.warning("Base config file not found: %s", base_path)
                config_data = {}
            else:
                config_data = self._load_yaml(base_path)

            # 环境覆盖配置按一级命名空间生效，例如 model/database/agent。
            scoped_override = env_override.get(name, {}) if isinstance(env_override, dict) else {}
            self._configs[name] = _deep_merge(config_data, scoped_override) if scoped_override else config_data

        # 配置 Schema 主要用于配置治理、校验或文档用途，因此单独放入 schema 命名空间。
        schema_path = self.config_dir / "schema" / "config_schema.yaml"
        self._configs["schema"] = self._load_yaml(schema_path) if schema_path.exists() else {}

    def _load_yaml(self, file_path: Path) -> dict[str, Any]:
        """读取单个 YAML 文件。

        Args:
            file_path: YAML 文件路径。

        Returns:
            解析后的字典；若文件为空，则返回空字典。
        """
        with open(file_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def get(self, key_path: str, default: Any = None) -> Any:
        """按点路径读取配置值。

        示例：`model.primary_model.provider`

        Args:
            key_path: 以点号分隔的配置路径。
            default: 当路径不存在时返回的默认值。

        Returns:
            命中的配置值，或默认值。
        """
        keys = key_path.split(".")
        value: Any = self._configs
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_with_env(self, key_path: str, env_key: str | None = None, default: Any = None) -> Any:
        """优先从环境变量读取配置，否则回退到配置文件。

        常用于敏感配置，如 API Key、数据库密码等。

        Args:
            key_path: 配置文件中的逻辑路径。
            env_key: 显式指定的环境变量名；为空时尝试读取 `{key_path}_env`。
            default: 未命中时的默认值。

        Returns:
            环境变量值或配置文件中的值。
        """
        if env_key is None:
            env_key = self.get(f"{key_path}_env")
        if env_key and env_key in os.environ:
            return os.environ[env_key]
        return self.get(key_path, default)

    def get_model_config(self, model_type: str = "primary") -> dict[str, Any]:
        """获取模型配置，并自动解析 API Key。

        Args:
            model_type: 模型类型，如 `primary`、`secondary`。

        Returns:
            可直接用于模型客户端初始化的配置字典。
        """
        config = dict(self.get(f"model.{model_type}_model", {}) or {})
        if "api_key_env" in config:
            config["api_key"] = os.environ.get(config["api_key_env"], "")
        return config

    def get_database_required_env_vars(self, db_type: str = "mysql") -> list[str]:
        """Return declared env var names referenced by a database config section.

        This method only inspects unified config declarations such as
        `config/base/database.yaml` and extracts `*_env` fields. It does not
        read environment variable values directly.

        Args:
            db_type: Database type, such as `mysql` or `redis`.

        Returns:
            A de-duplicated list of env var names in declaration order.
        """
        config = dict(self.get(f"database.{db_type}", {}) or {})
        env_keys: list[str] = []
        for key, value in config.items():
            if key.endswith("_env") and value:
                env_name = str(value)
                if env_name not in env_keys:
                    env_keys.append(env_name)
        return env_keys

    def get_database_config(self, db_type: str = "mysql") -> dict[str, Any]:
        """获取数据库配置，并将环境变量覆盖写入最终结果。

        Args:
            db_type: 数据库类型，如 `mysql`、`redis`。

        Returns:
            过滤掉 `*_env` 辅助字段后的数据库配置字典。
        """
        config = dict(self.get(f"database.{db_type}", {}) or {})
        for key in list(config.keys()):
            env_key = config.get(f"{key}_env")
            if env_key and env_key in os.environ:
                value = os.environ[env_key]
                # 端口在环境变量中是字符串，这里统一转换为整数，方便后续连接器直接使用。
                if key == "port":
                    value = int(value)
                config[key] = value
        return {key: value for key, value in config.items() if not key.endswith("_env")}

    def get_agent_config(self, agent_type: str) -> dict[str, Any]:
        """获取某个 Agent 的配置。

        返回结果由通用配置与具体 Agent 配置合并而成，后者优先级更高。

        Args:
            agent_type: Agent 类型，例如 `router`、`retrieval`。
        """
        common_config = self.get("agent.common", {}) or {}
        agent_config = self.get(f"agent.{agent_type}_agent", {}) or {}
        return {**common_config, **agent_config}

    def get_business_config(self, section: str | None = None, default: Any = None) -> Any:
        """获取业务配置。

        Args:
            section: 业务配置分组；为空时返回整个 `business` 节点。
            default: 未命中时的默认值。
        """
        if section:
            result = self.get(f"business.{section}", None)
            return default if result is None else result
        return self.get("business", default if default is not None else {})

    def get_tool_config(self, section: str | None = None, default: Any = None) -> Any:
        """获取工具相关配置。

        Args:
            section: 工具配置分组；为空时返回整个 `tools` 节点。
            default: 未命中时的默认值。
        """
        if section:
            result = self.get(f"tools.{section}", None)
            return default if result is None else result
        return self.get("tools", default if default is not None else {})

    def get_streaming_config(self) -> dict[str, Any]:
        """获取流式输出相关配置。"""
        return self.get("model.streaming", {}) or {}

    def get_retry_config(self) -> dict[str, Any]:
        """获取模型调用重试相关配置。"""
        return self.get("model.retry", {}) or {}

    def get_vector_store_config(self) -> dict[str, Any]:
        """获取向量库相关配置。"""
        return self.get("agent.vector_store", {}) or {}

    def get_conversation_history_config(self) -> dict[str, Any]:
        """Get conversation history config."""
        return self.get("agent.conversation_history", {}) or {}

    def validate_config(self) -> bool:
        """校验关键配置是否齐全。

        Returns:
            若关键配置都存在则返回 True，否则记录错误日志并返回 False。
        """
        required_configs = [
            "model.primary_model.provider",
            "model.primary_model.model_name",
            "agent.common",
            "database.mysql.host",
            "database.mysql.port",
            "database.mysql.database",
            "database.mysql.username",
        ]
        missing = [key for key in required_configs if self.get(key) is None]
        if missing:
            logger.error("Required config missing: %s", ", ".join(missing))
            return False
        return True

    def validate_model_config(self, model_type: str = "primary") -> bool:
        """校验某类模型配置是否完整。"""
        config = self.get_model_config(model_type)
        return all(config.get(field) for field in ["provider", "model_name", "api_key"])

    def validate_database_config(self, db_type: str = "mysql") -> bool:
        """校验数据库配置是否完整。

        Redis 与关系型数据库要求的关键字段不同，因此分别处理。
        """
        config = self.get_database_config(db_type)
        required = ["host", "port"] if db_type == "redis" else ["host", "port", "database", "username", "password"]
        return all(config.get(field) for field in required)

    def reload(self):
        """清空缓存并重新加载配置。"""
        self._configs.clear()
        self._load_all_configs()

    def __repr__(self) -> str:
        """返回便于调试的对象描述。"""
        return f"ConfigManager(config_dir='{self.config_dir}')"


# 模块级单例缓存，避免在项目各处重复实例化配置管理器。
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取 `ConfigManager` 单例。"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

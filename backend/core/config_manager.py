"""Centralized configuration loading and validation."""

from backend.core.env_loader import load_environment

load_environment()

import logging
import os
from pathlib import Path
from typing import Any, Optional

import yaml


logger = logging.getLogger(__name__)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ConfigManager:
    def __init__(self, config_dir: str | None = None):
        if config_dir is None:
            from backend.utils.path_utils import find_project_root

            project_root = find_project_root(Path(__file__).parent)
            config_dir = project_root / "config"

        self.config_dir = Path(config_dir)
        self._configs: dict[str, Any] = {}
        self._load_all_configs()

    def _load_all_configs(self):
        env_name = os.getenv("APP_ENV", os.getenv("ENV", "development"))
        base_files = {
            "model": "model.yaml",
            "database": "database.yaml",
            "agent": "agent.yaml",
            "business": "business.yaml",
            "tools": "tools.yaml",
        }
        legacy_files = {
            "model": "model_config.yaml",
            "database": "database_config.yaml",
            "agent": "agent_config.yaml",
            "business": "business_config.yaml",
            "tools": "tools_config.yaml",
        }

        env_path = self.config_dir / "env" / f"{env_name}.yaml"
        env_override = self._load_yaml(env_path) if env_path.exists() else {}

        for name in base_files:
            base_path = self.config_dir / "base" / base_files[name]
            legacy_path = self.config_dir / legacy_files[name]
            config_data = self._load_yaml(base_path) if base_path.exists() else {}
            if not config_data and legacy_path.exists():
                config_data = self._load_yaml(legacy_path)

            scoped_override = env_override.get(name, {}) if isinstance(env_override, dict) else {}
            self._configs[name] = _deep_merge(config_data, scoped_override) if scoped_override else config_data

        schema_path = self.config_dir / "schema" / "config_schema.yaml"
        self._configs["schema"] = self._load_yaml(schema_path) if schema_path.exists() else {}

    def _load_yaml(self, file_path: Path) -> dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        value: Any = self._configs
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def get_with_env(self, key_path: str, env_key: str | None = None, default: Any = None) -> Any:
        if env_key is None:
            env_key = self.get(f"{key_path}_env")
        if env_key and env_key in os.environ:
            return os.environ[env_key]
        return self.get(key_path, default)

    def get_model_config(self, model_type: str = "primary") -> dict[str, Any]:
        config = dict(self.get(f"model.{model_type}_model", {}) or {})
        if "api_key_env" in config:
            config["api_key"] = os.environ.get(config["api_key_env"], "")
        return config

    def get_database_config(self, db_type: str = "mysql") -> dict[str, Any]:
        config = dict(self.get(f"database.{db_type}", {}) or {})
        for key in list(config.keys()):
            env_key = config.get(f"{key}_env")
            if env_key and env_key in os.environ:
                value = os.environ[env_key]
                if key == "port":
                    value = int(value)
                config[key] = value
        return {key: value for key, value in config.items() if not key.endswith("_env")}

    def get_agent_config(self, agent_type: str) -> dict[str, Any]:
        common_config = self.get("agent.common", {}) or {}
        agent_config = self.get(f"agent.{agent_type}_agent", {}) or {}
        return {**common_config, **agent_config}

    def get_business_config(self, section: str | None = None, default: Any = None) -> Any:
        if section:
            result = self.get(f"business.{section}", None)
            return default if result is None else result
        return self.get("business", default if default is not None else {})

    def get_tool_config(self, section: str | None = None, default: Any = None) -> Any:
        if section:
            result = self.get(f"tools.{section}", None)
            return default if result is None else result
        return self.get("tools", default if default is not None else {})

    def get_streaming_config(self) -> dict[str, Any]:
        return self.get("model.streaming", {}) or {}

    def get_retry_config(self) -> dict[str, Any]:
        return self.get("model.retry", {}) or {}

    def get_vector_store_config(self) -> dict[str, Any]:
        return self.get("agent.vector_store", {}) or {}

    def get_conversation_history_config(self) -> dict[str, Any]:
        return self.get("agent.conversation_history", self.get("conversation_history", {})) or {}

    def validate_config(self) -> bool:
        required_configs = [
            "model.primary_model.provider",
            "model.primary_model.model_name",
            "agent.common",
            "agent.router_agent",
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
        config = self.get_model_config(model_type)
        return all(config.get(field) for field in ["provider", "model_name", "api_key"])

    def validate_database_config(self, db_type: str = "mysql") -> bool:
        config = self.get_database_config(db_type)
        required = ["host", "port"] if db_type == "redis" else ["host", "port", "database", "username", "password"]
        return all(config.get(field) for field in required)

    def reload(self):
        self._configs.clear()
        self._load_all_configs()

    def __repr__(self) -> str:
        return f"ConfigManager(config_dir='{self.config_dir}')"


_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager

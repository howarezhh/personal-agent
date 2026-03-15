"""Prompt 管理模块。

该模块负责：
1. 从统一目录批量加载 Prompt YAML 文件；
2. 同时兼容旧版 Prompt 文档与带元信息的版本化文档；
3. 提供 Prompt 查询、变量格式化、消息构建等能力；
4. 维护 Prompt 元信息和加载校验错误，便于治理与排查。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# 当前模块使用的日志记录器。
logger = logging.getLogger(__name__)


class PromptManager:
    """统一 Prompt 管理器。"""

    # 版本化 Prompt 文档必须包含的字段集合。
    REQUIRED_VERSIONED_FIELDS = {
        "name",
        "version",
        "agent",
        "scene",
        "input_variables",
        "output_requirements",
        "applicable_models",
        "change_log",
        "prompts",
    }

    def __init__(self, prompts_dir: str | Path | None = None, *, strict: bool = False):
        """初始化 Prompt 管理器。

        Args:
            prompts_dir: Prompt 根目录；为空时自动定位到项目配置目录中的 `config/prompts`。
            strict: 严格模式。若存在校验错误，则在初始化时直接抛出异常。
        """
        if prompts_dir is None:
            from backend.utils.path_utils import find_project_root

            project_root = find_project_root(Path(__file__).parent)
            prompts_dir = project_root / "config" / "prompts"

        # `_prompts` 用于保存真正可被业务使用的 Prompt 文本内容。
        self.prompts_dir = Path(prompts_dir)
        self.strict = strict
        self._prompts: Dict[str, Dict[str, Any]] = {}
        # `_metadata` 用于保存版本、适用场景、输入变量等治理信息。
        self._metadata: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # `_validation_errors` 用于累计加载和校验过程中出现的问题。
        self._validation_errors: list[str] = []
        self._load_all_prompts()
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def _load_all_prompts(self):
        """扫描目录并加载全部 Prompt 文档。"""
        if not self.prompts_dir.exists():
            logger.warning("Prompts directory not found: %s", self.prompts_dir)
            return

        loaded_count = 0
        for prompt_file in sorted(self.prompts_dir.rglob("*.yaml")):
            prompt_data = self._load_yaml(prompt_file)
            if not prompt_data:
                logger.warning("Empty or invalid prompt file: %s", prompt_file)
                continue

            # 根据文档结构自动区分“旧版 Prompt 文件”与“版本化 Prompt 文件”。
            if self._is_versioned_document(prompt_data):
                self._load_versioned_document(prompt_file, prompt_data)
            else:
                self._load_legacy_document(prompt_file, prompt_data)
            loaded_count += 1

        if loaded_count == 0:
            logger.warning("No prompt files found in: %s", self.prompts_dir)

    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """读取单个 Prompt YAML 文件。

        Args:
            file_path: Prompt 文件路径。

        Returns:
            解析结果字典；发生异常时返回空字典并记录校验错误。
        """
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except Exception as error:
            logger.error("Error loading prompt file %s: %s", file_path, error)
            self._validation_errors.append(f"{file_path}: {error}")
            return {}

    def _is_versioned_document(self, prompt_data: Dict[str, Any]) -> bool:
        """判断当前 Prompt 文档是否为带元信息的版本化结构。"""
        return isinstance(prompt_data, dict) and "prompts" in prompt_data

    def _load_legacy_document(self, prompt_file: Path, prompt_data: Dict[str, Any]) -> None:
        """加载旧版 Prompt 文档。

        旧版文档主要依赖文件名推断 agent_type，并直接把 YAML 内容并入对应 Agent 的 Prompt 集合。
        """
        stem = prompt_file.stem
        if stem.endswith("_prompts"):
            agent_type = stem.replace("_prompts", "")
        else:
            parts = stem.split("_")
            if len(parts) < 3:
                return
            agent_type = parts[0]

        existing = self._prompts.get(agent_type, {})
        if isinstance(existing, dict) and isinstance(prompt_data, dict):
            existing.update(prompt_data)
            self._prompts[agent_type] = existing
        else:
            self._prompts[agent_type] = prompt_data
        logger.info("Loaded legacy prompts for agent type: %s", agent_type)

    def _load_versioned_document(self, prompt_file: Path, prompt_data: Dict[str, Any]) -> None:
        """加载版本化 Prompt 文档并进行结构校验。"""
        missing = sorted(self.REQUIRED_VERSIONED_FIELDS - set(prompt_data.keys()))
        if missing:
            error = f"{prompt_file}: missing required fields {', '.join(missing)}"
            logger.error(error)
            self._validation_errors.append(error)
            return

        agent_type = str(prompt_data["agent"])
        scene = str(prompt_data["scene"])
        prompts = prompt_data.get("prompts") or {}
        if not isinstance(prompts, dict) or not prompts:
            error = f"{prompt_file}: prompts must be a non-empty mapping"
            logger.error(error)
            self._validation_errors.append(error)
            return

        # 真实 Prompt 内容按 agent_type 聚合保存，供运行时快速读取。
        self._prompts.setdefault(agent_type, {}).update(prompts)
        # 治理元信息按 agent_type + scene 保存，便于查询版本与适用场景。
        self._metadata.setdefault(agent_type, {})[scene] = {
            key: value
            for key, value in prompt_data.items()
            if key != "prompts"
        }
        logger.info("Loaded versioned prompts for agent=%s scene=%s", agent_type, scene)

    def get_prompt(self, prompt_key: str, default: str | None = None) -> str:
        """按点路径获取 Prompt 文本。

        Args:
            prompt_key: Prompt 路径，例如 `router.router_system_prompt`。
            default: 未命中时返回的默认值。
        """
        keys = prompt_key.split(".")
        value: Any = self._prompts
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default if default is not None else ""
        return str(value) if value is not None else (default if default is not None else "")

    def format_prompt(self, prompt_key: str, **kwargs) -> str:
        """读取并格式化 Prompt 模板。

        若格式化失败，则返回原模板，以便调用方至少能获得可排查的原始 Prompt。
        """
        template = self.get_prompt(prompt_key)
        if not template:
            logger.warning("Prompt template not found: %s", prompt_key)
            return ""
        try:
            return template.format(**kwargs)
        except Exception as error:
            logger.warning("Error formatting prompt %s: %s", prompt_key, error)
            return template

    def format_conversation_history(self, messages: List[Dict[str, str]], prompt_type: str = "router", max_messages: int = 10) -> str:
        """将对话历史格式化为可注入 Prompt 的文本块。

        Args:
            messages: 消息列表，每项至少包含 `role` 和 `content`。
            prompt_type: Prompt 类型，对应不同 Agent 的历史格式模板。
            max_messages: 最多保留多少条最近消息，避免上下文过长。
        """
        if not messages:
            return self.get_prompt(f"{prompt_type}.no_history_placeholder", "（这是新对话的第一条消息）")

        format_template = self.get_prompt(f"{prompt_type}.conversation_history_format", "{role}: {content}")
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        formatted_messages: list[str] = []
        for msg in recent_messages:
            try:
                formatted_messages.append(format_template.format(role=msg.get("role", "unknown"), content=msg.get("content", "")))
            except Exception:
                # 单条消息格式化失败时直接跳过，避免整段历史都不可用。
                continue
        return "\n".join(formatted_messages)

    def get_system_prompt(self, agent_type: str) -> str:
        """获取指定 Agent 的系统提示词。"""
        return self.get_prompt(f"{agent_type}.{agent_type}_system_prompt", "")

    def get_user_prompt_template(self, agent_type: str) -> str:
        """获取指定 Agent 的用户提示词模板。"""
        return self.get_prompt(f"{agent_type}.{agent_type}_user_prompt", "")

    def build_messages(self, agent_type: str, user_content: str, conversation_history: List[Dict[str, str]] | None = None, **kwargs) -> List[Dict[str, str]]:
        """构建发送给大模型的标准消息列表。

        该方法会自动：
        - 注入系统提示词；
        - 格式化最近的会话历史；
        - 使用用户模板拼装最终 user message。
        """
        messages = []
        system_prompt = self.get_system_prompt(agent_type)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        history_str = self.format_conversation_history(conversation_history, prompt_type=agent_type) if conversation_history else ""
        user_template = self.get_user_prompt_template(agent_type)
        if user_template:
            variables = {"question": user_content, "conversation_history": history_str, **kwargs}
            messages.append({"role": "user", "content": self.format_prompt(f"{agent_type}.{agent_type}_user_prompt", **variables)})
        else:
            # 如果没有配置模板，则退化为直接传递用户原始输入。
            messages.append({"role": "user", "content": user_content})
        return messages

    def get_prompt_metadata(self, agent_type: str, scene: str | None = None) -> Dict[str, Any]:
        """获取 Prompt 元信息。

        Args:
            agent_type: Agent 类型。
            scene: 可选场景名；若为空则返回该 Agent 下全部场景元信息。
        """
        if scene:
            return dict((self._metadata.get(agent_type) or {}).get(scene, {}))
        return dict(self._metadata.get(agent_type, {}))

    def validate_versioned_prompts(self) -> list[str]:
        """返回当前累计的 Prompt 校验错误列表。"""
        return list(self._validation_errors)

    def reload(self):
        """清空缓存并重新加载全部 Prompt。"""
        self._prompts.clear()
        self._metadata.clear()
        self._validation_errors.clear()
        self._load_all_prompts()
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def list_available_prompts(self, agent_type: str | None = None) -> List[str]:
        """列出可用 Prompt 键。

        Args:
            agent_type: 指定 Agent 类型时，仅返回该 Agent 下的 Prompt 名称。
        """
        if agent_type:
            return list((self._prompts.get(agent_type) or {}).keys())
        return [f"{current_agent}.{key}" for current_agent, prompts in self._prompts.items() for key in prompts.keys()]

    def __repr__(self) -> str:
        """返回便于调试的对象描述。"""
        return f"PromptManager(prompts_dir='{self.prompts_dir}')"


# 模块级单例缓存，供业务代码全局复用。
_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取 `PromptManager` 单例。"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

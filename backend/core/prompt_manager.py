"""Prompt manager with legacy and versioned prompt support."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


logger = logging.getLogger(__name__)


class PromptManager:
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
        if prompts_dir is None:
            from backend.utils.path_utils import find_project_root

            project_root = find_project_root(Path(__file__).parent)
            prompts_dir = project_root / "config" / "prompts"

        self.prompts_dir = Path(prompts_dir)
        self.strict = strict
        self._prompts: Dict[str, Dict[str, Any]] = {}
        self._metadata: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._validation_errors: list[str] = []
        self._load_all_prompts()
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def _load_all_prompts(self):
        if not self.prompts_dir.exists():
            logger.warning("Prompts directory not found: %s", self.prompts_dir)
            return

        loaded_count = 0
        for prompt_file in sorted(self.prompts_dir.rglob("*.yaml")):
            prompt_data = self._load_yaml(prompt_file)
            if not prompt_data:
                logger.warning("Empty or invalid prompt file: %s", prompt_file)
                continue

            if self._is_versioned_document(prompt_data):
                self._load_versioned_document(prompt_file, prompt_data)
            else:
                self._load_legacy_document(prompt_file, prompt_data)
            loaded_count += 1

        if loaded_count == 0:
            logger.warning("No prompt files found in: %s", self.prompts_dir)

    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except Exception as error:
            logger.error("Error loading prompt file %s: %s", file_path, error)
            self._validation_errors.append(f"{file_path}: {error}")
            return {}

    def _is_versioned_document(self, prompt_data: Dict[str, Any]) -> bool:
        return isinstance(prompt_data, dict) and "prompts" in prompt_data

    def _load_legacy_document(self, prompt_file: Path, prompt_data: Dict[str, Any]) -> None:
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

        self._prompts.setdefault(agent_type, {}).update(prompts)
        self._metadata.setdefault(agent_type, {})[scene] = {
            key: value
            for key, value in prompt_data.items()
            if key != "prompts"
        }
        logger.info("Loaded versioned prompts for agent=%s scene=%s", agent_type, scene)

    def get_prompt(self, prompt_key: str, default: str | None = None) -> str:
        keys = prompt_key.split(".")
        value: Any = self._prompts
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default if default is not None else ""
        return str(value) if value is not None else (default if default is not None else "")

    def format_prompt(self, prompt_key: str, **kwargs) -> str:
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
        if not messages:
            return self.get_prompt(f"{prompt_type}.no_history_placeholder", "（这是新对话的第一条消息）")

        format_template = self.get_prompt(f"{prompt_type}.conversation_history_format", "{role}: {content}")
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        formatted_messages: list[str] = []
        for msg in recent_messages:
            try:
                formatted_messages.append(format_template.format(role=msg.get("role", "unknown"), content=msg.get("content", "")))
            except Exception:
                continue
        return "\n".join(formatted_messages)

    def get_system_prompt(self, agent_type: str) -> str:
        return self.get_prompt(f"{agent_type}.{agent_type}_system_prompt", "")

    def get_user_prompt_template(self, agent_type: str) -> str:
        return self.get_prompt(f"{agent_type}.{agent_type}_user_prompt", "")

    def build_messages(self, agent_type: str, user_content: str, conversation_history: List[Dict[str, str]] | None = None, **kwargs) -> List[Dict[str, str]]:
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
            messages.append({"role": "user", "content": user_content})
        return messages

    def get_prompt_metadata(self, agent_type: str, scene: str | None = None) -> Dict[str, Any]:
        if scene:
            return dict((self._metadata.get(agent_type) or {}).get(scene, {}))
        return dict(self._metadata.get(agent_type, {}))

    def validate_versioned_prompts(self) -> list[str]:
        return list(self._validation_errors)

    def reload(self):
        self._prompts.clear()
        self._metadata.clear()
        self._validation_errors.clear()
        self._load_all_prompts()
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def list_available_prompts(self, agent_type: str | None = None) -> List[str]:
        if agent_type:
            return list((self._prompts.get(agent_type) or {}).keys())
        return [f"{current_agent}.{key}" for current_agent, prompts in self._prompts.items() for key in prompts.keys()]

    def __repr__(self) -> str:
        return f"PromptManager(prompts_dir='{self.prompts_dir}')"


_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

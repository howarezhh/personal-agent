# -*- coding: utf-8 -*-
"""Prompt 管理器。

本模块继续以 `config/prompts/` 为 Prompt 唯一事实源，
并在原有读取/格式化能力基础上，补充面向 LangChain 的模板工厂能力：

1. 读取版本化 Prompt 文档；
2. 生成 `PromptTemplate`；
3. 生成 `ChatPromptTemplate`；
4. 生成 `ChatPromptValue` 与项目内部 message 数组；
5. 保留旧接口，避免业务层在当前阶段发生不必要扩散。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.prompt_values import ChatPromptValue


logger = logging.getLogger(__name__)


class PromptManager:
    """统一加载、校验并分发项目 Prompt。"""

    # REQUIRED_VERSIONED_FIELDS：版本化 Prompt 文档必须包含的字段集合。
    # 该集合用于在加载阶段做基础契约校验，避免业务运行到一半才发现 Prompt 文档不完整。
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
        """初始化 Prompt 管理器。"""
        if prompts_dir is None:
            from backend.utils.path_utils import find_project_root

            # project_root：项目根目录，用于定位统一的 Prompt 配置目录。
            project_root = find_project_root(Path(__file__).parent)
            prompts_dir = project_root / "config" / "prompts"

        # prompts_dir：Prompt 配置根目录，所有 Prompt 必须从这里统一加载。
        self.prompts_dir = Path(prompts_dir)
        # strict：是否开启严格模式；开启后若存在校验错误会直接抛异常。
        self.strict = strict
        # _prompts：Prompt 正文缓存，按 agent_type 分组存放。
        self._prompts: Dict[str, Dict[str, Any]] = {}
        # _metadata：Prompt 元信息缓存，按 agent_type -> scene 分层存放。
        self._metadata: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # _validation_errors：加载和校验过程中累计的错误列表。
        self._validation_errors: list[str] = []
        # 初始化时立即加载全部 Prompt，保持运行期读取为内存访问。
        self._load_all_prompts()
        # 严格模式下只要有校验错误就立刻失败，避免系统带病运行。
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def _load_all_prompts(self) -> None:
        """加载目录下全部版本化 Prompt 文档。"""
        if not self.prompts_dir.exists():
            logger.warning("Prompts directory not found: %s", self.prompts_dir)
            return

        # loaded_count：成功进入加载流程的 Prompt 文件数量，用于最终做空目录告警。
        loaded_count = 0
        for prompt_file in sorted(self.prompts_dir.rglob("*.yaml")):
            # 逐个读取 YAML 文件，保证错误可精确定位到具体文件。
            prompt_data = self._load_yaml(prompt_file)
            if not prompt_data:
                logger.warning("Empty or invalid prompt file: %s", prompt_file)
                continue
            # 核心逻辑：读取成功后继续做版本化文档结构校验并写入缓存。
            self._load_versioned_document(prompt_file, prompt_data)
            loaded_count += 1

        if loaded_count == 0:
            logger.warning("No prompt files found in: %s", self.prompts_dir)

    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """读取单个 YAML Prompt 文档。"""
        try:
            # 显式使用 utf-8 编码读取，避免中文 Prompt 内容乱码。
            with open(file_path, "r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except Exception as error:
            logger.error("Error loading prompt file %s: %s", file_path, error)
            self._validation_errors.append(f"{file_path}: {error}")
            return {}

    def _load_versioned_document(self, prompt_file: Path, prompt_data: Dict[str, Any]) -> None:
        """校验并加载单个版本化 Prompt 文档。"""
        # missing：当前 Prompt 文档缺失的必填字段集合。
        missing = sorted(self.REQUIRED_VERSIONED_FIELDS - set(prompt_data.keys()))
        if missing:
            error = f"{prompt_file}: missing required fields {', '.join(missing)}"
            logger.error(error)
            self._validation_errors.append(error)
            return

        # agent_type：Prompt 所属的 Agent 类型，例如 router / retrieval / generation。
        agent_type = str(prompt_data["agent"])
        # scene：Prompt 的场景标识，用于元信息分类与版本追踪。
        scene = str(prompt_data["scene"])
        # prompts：Prompt 正文区，通常是一个键值映射，而不是单个字符串。
        prompts = prompt_data.get("prompts") or {}
        if not isinstance(prompts, dict) or not prompts:
            error = f"{prompt_file}: prompts must be a non-empty mapping"
            logger.error(error)
            self._validation_errors.append(error)
            return

        # 核心逻辑：Prompt 正文按 agent_type 聚合，便于通过 `agent.key` 方式统一读取。
        self._prompts.setdefault(agent_type, {}).update(prompts)
        # 元信息单独缓存，避免与正文混在一起，便于后续查询版本、模型适用范围、变更记录等信息。
        self._metadata.setdefault(agent_type, {})[scene] = {
            key: value
            for key, value in prompt_data.items()
            if key != "prompts"
        }
        logger.info("Loaded versioned prompts for agent=%s scene=%s", agent_type, scene)

    def get_prompt(self, prompt_key: str, default: str | None = None) -> str:
        """根据点分路径读取 Prompt 原文。"""
        # keys：支持使用 `agent.prompt_key` 这种点分路径访问缓存内容。
        keys = prompt_key.split(".")
        # value：遍历中的当前节点，初始值为整棵 Prompt 缓存树。
        value: Any = self._prompts
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                # 若路径任一层不存在，则返回默认值或空字符串，保持调用层行为稳定。
                return default if default is not None else ""
        return str(value) if value is not None else (default if default is not None else "")

    def get_prompt_template(self, prompt_key: str, default: str | None = None) -> PromptTemplate:
        """返回 LangChain `PromptTemplate`。

        这样业务层可以直接把模板对象交给模型交互层，
        不再需要先把 Prompt 渲染成字符串再传递。
        """
        # template_text：从统一缓存中读取到的 Prompt 原文。
        template_text = self.get_prompt(prompt_key, default=default)
        if not template_text:
            logger.warning("Prompt template not found: %s", prompt_key)
        # 核心逻辑：统一转换为 LangChain PromptTemplate，避免业务层自行拼接模板字符串。
        return PromptTemplate.from_template(template_text or "")

    def render_prompt(self, prompt_key: str, **kwargs: Any) -> str:
        """渲染单条 Prompt 模板为字符串。

        该方法是统一的显式渲染入口：
        - Prompt 来源仍然只能是配置文件；
        - 变量渲染统一通过 `PromptTemplate` 完成；
        - 业务层统一调用当前入口，不再分散定义其它渲染方式。
        """
        # prompt_template：标准化后的 PromptTemplate 对象。
        prompt_template = self.get_prompt_template(prompt_key)
        try:
            # 使用 LangChain 的模板渲染能力统一完成变量替换。
            return prompt_template.invoke(kwargs).to_string()
        except Exception as error:
            # 若渲染失败，则退回原始 Prompt 文本，避免上层直接崩溃。
            logger.warning("Error rendering prompt %s: %s", prompt_key, error)
            return self.get_prompt(prompt_key)

    def format_conversation_history(
        self,
        messages: List[Dict[str, str]],
        prompt_type: str = "router",
        max_messages: int = 10,
    ) -> str:
        """把对话历史渲染为 Prompt 可消费的文本。"""
        if not messages:
            # 没有历史消息时返回可配置的占位文案，避免 Prompt 中历史变量为空导致语义不完整。
            return self.get_prompt(f"{prompt_type}.no_history_placeholder", "（这是新对话的第一条消息）")

        # format_template：单条历史消息的格式模板。
        format_template = self.get_prompt(f"{prompt_type}.conversation_history_format", "{role}: {content}")
        # recent_messages：只保留最近 N 条消息，避免 Prompt 上下文无限膨胀。
        recent_messages = messages[-max_messages:] if len(messages) > max_messages else messages
        # formatted_messages：格式化后的历史消息文本列表。
        formatted_messages: list[str] = []
        for msg in recent_messages:
            try:
                # 核心逻辑：逐条按统一模板渲染 role/content，形成最终历史上下文文本。
                formatted_messages.append(
                    format_template.format(role=msg.get("role", "unknown"), content=msg.get("content", ""))
                )
            except Exception:
                # 单条历史消息格式异常时跳过，避免影响整段历史构建。
                continue
        return "\n".join(formatted_messages)

    def get_system_prompt(self, agent_type: str) -> str:
        """读取某类 Agent 的系统 Prompt。"""
        # 统一按约定命名规则读取系统 Prompt。
        return self.get_prompt(f"{agent_type}.{agent_type}_system_prompt", "")

    def get_user_prompt_template(self, agent_type: str) -> str:
        """读取某类 Agent 的用户 Prompt 原文。"""
        # 统一按约定命名规则读取用户 Prompt 模板原文。
        return self.get_prompt(f"{agent_type}.{agent_type}_user_prompt", "")

    def build_chat_prompt_template(
        self,
        agent_type: str,
        *,
        system_prompt_key: str | None = None,
        user_prompt_key: str | None = None,
    ) -> ChatPromptTemplate:
        """构造 Agent 级 `ChatPromptTemplate`。

        默认约定：
        - system key: `{agent_type}.{agent_type}_system_prompt`
        - user key: `{agent_type}.{agent_type}_user_prompt`
        """
        # resolved_system_key / resolved_user_key：允许调用方覆盖默认 Prompt 键。
        resolved_system_key = system_prompt_key or f"{agent_type}.{agent_type}_system_prompt"
        resolved_user_key = user_prompt_key or f"{agent_type}.{agent_type}_user_prompt"

        # template_messages：ChatPromptTemplate 所需的消息模板定义列表。
        template_messages: List[tuple[str, str]] = []
        # system_prompt：系统角色 Prompt 文本。
        system_prompt = self.get_prompt(resolved_system_key, "")
        # user_prompt：用户角色 Prompt 文本，默认保底为 `{question}`。
        user_prompt = self.get_prompt(resolved_user_key, "{question}")

        if system_prompt:
            template_messages.append(("system", system_prompt))
        # 至少保留一条 user 模板消息，确保模板可被正常调用。
        template_messages.append(("user", user_prompt or "{question}"))
        return ChatPromptTemplate.from_messages(template_messages)

    def build_chat_prompt_value(
        self,
        agent_type: str,
        user_content: str,
        conversation_history: List[Dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> ChatPromptValue:
        """构造 LangChain `ChatPromptValue`。"""
        # chat_prompt_template：当前 Agent 对应的聊天模板。
        chat_prompt_template = self.build_chat_prompt_template(agent_type)
        # history_str：把历史消息压缩为 Prompt 可消费的字符串片段。
        history_str = self.format_conversation_history(conversation_history, prompt_type=agent_type) if conversation_history else ""
        # variables：统一注入模板变量，question / conversation_history 是约定保留变量。
        variables = {"question": user_content, "conversation_history": history_str, **kwargs}
        return chat_prompt_template.invoke(variables)

    def build_chat_messages(
        self,
        agent_type: str,
        user_content: str,
        conversation_history: List[Dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> List[Dict[str, str]]:
        """基于 `ChatPromptTemplate` 构造项目内部消息数组。"""
        # 先构造 LangChain ChatPromptValue，再统一映射为项目内部消息结构。
        prompt_value = self.build_chat_prompt_value(
            agent_type=agent_type,
            user_content=user_content,
            conversation_history=conversation_history,
            **kwargs,
        )
        # messages：最终产出的项目内部标准消息数组。
        messages: List[Dict[str, str]] = []
        for message in prompt_value.to_messages():
            # message_type：LangChain 消息对象的原生角色类型。
            message_type = getattr(message, "type", "user")
            if message_type == "system":
                role = "system"
            elif message_type in {"ai", "assistant"}:
                role = "assistant"
            else:
                role = "user"
            # 核心逻辑：统一把框架消息结构收敛成项目内部约定的 role/content 格式。
            messages.append({"role": role, "content": str(getattr(message, "content", ""))})
        return messages

    def get_prompt_metadata(self, agent_type: str, scene: str | None = None) -> Dict[str, Any]:
        """读取 Prompt 元信息。"""
        # scene 存在时返回具体场景元信息，否则返回该 agent_type 下全部场景元信息。
        if scene:
            return dict((self._metadata.get(agent_type) or {}).get(scene, {}))
        return dict(self._metadata.get(agent_type, {}))

    def validate_versioned_prompts(self) -> list[str]:
        """返回加载阶段积累的校验错误。"""
        # 返回副本，避免调用方误修改内部错误缓存。
        return list(self._validation_errors)

    def reload(self) -> None:
        """清空缓存并重新加载 Prompt。"""
        # 重新加载前先清空全部缓存，确保不会混入旧数据。
        self._prompts.clear()
        self._metadata.clear()
        self._validation_errors.clear()
        self._load_all_prompts()
        # 严格模式下，重新加载后若仍有错误则继续抛异常。
        if self.strict and self._validation_errors:
            raise ValueError("; ".join(self._validation_errors))

    def list_available_prompts(self, agent_type: str | None = None) -> List[str]:
        """列出可用 Prompt 键。"""
        if agent_type:
            # 仅列出某个 agent_type 下的 Prompt key。
            return list((self._prompts.get(agent_type) or {}).keys())
        # 否则返回 `agent.key` 形式的完整键名列表，方便排查与调试。
        return [f"{current_agent}.{key}" for current_agent, prompts in self._prompts.items() for key in prompts.keys()]

    def __repr__(self) -> str:
        return f"PromptManager(prompts_dir='{self.prompts_dir}')"


_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取 `PromptManager` 单例。"""
    global _prompt_manager
    # 懒加载单例：首次使用时才初始化 PromptManager。
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

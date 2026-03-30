# -*- coding: utf-8 -*-
"""Prompt 管理器。

本模块继续以 `config/prompts/` 为 Prompt 唯一事实源，
并在原有读取/格式化能力基础上，补充面向 LangChain 的模板工厂能力：

1. 读取版本化 Prompt 文档；
2. 生成 `PromptTemplate`；
3. 生成 `ChatPromptTemplate`；
4. 生成 `ChatPromptValue` 与项目内部 message 数组；
5. 统一由显式的 ChatPromptTemplate 调用参数进入模型交互层。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
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
    # REQUIRED_CHANGE_LOG_FIELDS：每条变更记录必须具备的字段，避免 Prompt 版本追踪失真。
    REQUIRED_CHANGE_LOG_FIELDS = {"version", "date", "summary"}
    # PROMPT_VARIABLE_PATTERN：用于提取 Prompt 模板中的显式变量占位符。
    PROMPT_VARIABLE_PATTERN = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})")
    # FULL_PROMPT_KEY_PATTERN：用于从代码中提取完整 Prompt key 字面量。
    FULL_PROMPT_KEY_PATTERN = re.compile(
        r'["\']((?:router|retrieval|generation|file_processor|tool|planner|critic)\.[a-zA-Z0-9_\.]+)["\']'
    )
    # LOCAL_PROMPT_CALL_PATTERN：用于识别 `_get_prompt("local_key")` 这种局部 Prompt 调用。
    LOCAL_PROMPT_CALL_PATTERN = re.compile(r'_get_prompt\(\s*["\']([^"\']+)["\']')

    def __init__(
        self,
        prompts_dir: str | Path | None = None,
        *,
        strict: bool = False,
        project_root: str | Path | None = None,
    ):
        """初始化 Prompt 管理器。"""
        if prompts_dir is None:
            from backend.utils.path_utils import find_project_root

            # project_root：项目根目录，用于定位统一的 Prompt 配置目录。
            project_root = Path(project_root) if project_root is not None else find_project_root(Path(__file__).parent)
            prompts_dir = project_root / "config" / "prompts"

        # prompts_dir：Prompt 配置根目录，所有 Prompt 必须从这里统一加载。
        self.prompts_dir = Path(prompts_dir)
        # project_root：项目根目录，用于执行未引用 Prompt 校验等工程级校验逻辑。
        self.project_root = Path(project_root) if project_root is not None else self._infer_project_root()
        # strict：是否开启严格模式；开启后若存在校验错误会直接抛异常。
        self.strict = strict
        # _prompts：Prompt 正文缓存，按 agent_type 分组存放。
        self._prompts: Dict[str, Dict[str, Any]] = {}
        # _metadata：Prompt 元信息缓存，按 agent_type -> scene 分层存放。
        self._metadata: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # _prompt_sources：记录每个 Prompt key 来自哪个文件，便于做重复定义与未引用排查。
        self._prompt_sources: Dict[str, Dict[str, Path]] = {}
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
            return

        # 全部 Prompt 加载完成后，再执行跨文件级别的统一校验。
        self._validate_unused_prompts()

    def _infer_project_root(self) -> Path | None:
        """根据 Prompt 目录推断项目根目录。"""
        resolved_dir = self.prompts_dir.resolve()
        parents = [resolved_dir, *resolved_dir.parents]
        for current_path in parents:
            if (current_path / "backend").exists() and (current_path / "config").exists():
                return current_path
        return None

    def _record_validation_error(self, message: str) -> None:
        """统一记录 Prompt 校验错误。"""
        logger.error(message)
        self._validation_errors.append(message)

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
            self._record_validation_error(error)
            return

        # `input_variables`：Prompt 文件声明的输入变量集合，必须是字符串列表。
        input_variables = prompt_data.get("input_variables")
        if not isinstance(input_variables, list) or any(not isinstance(item, str) for item in input_variables):
            self._record_validation_error(f"{prompt_file}: input_variables must be a list of strings")
            return

        # `change_log`：Prompt 变更记录，必须保证结构完整，便于版本治理。
        change_log = prompt_data.get("change_log")
        if not isinstance(change_log, list) or not change_log:
            self._record_validation_error(f"{prompt_file}: change_log must be a non-empty list")
            return
        for index, change_item in enumerate(change_log):
            if not isinstance(change_item, dict):
                self._record_validation_error(f"{prompt_file}: change_log[{index}] must be a mapping")
                return
            missing_change_fields = sorted(self.REQUIRED_CHANGE_LOG_FIELDS - set(change_item.keys()))
            if missing_change_fields:
                self._record_validation_error(
                    f"{prompt_file}: change_log[{index}] missing fields {', '.join(missing_change_fields)}"
                )
                return

        # agent_type：Prompt 所属的 Agent 类型，例如 router / retrieval / generation / planner / critic。
        agent_type = str(prompt_data["agent"])
        # scene：Prompt 的场景标识，用于元信息分类与版本追踪。
        scene = str(prompt_data["scene"])
        # prompts：Prompt 正文区，通常是一个键值映射，而不是单个字符串。
        prompts = prompt_data.get("prompts") or {}
        if not isinstance(prompts, dict) or not prompts:
            error = f"{prompt_file}: prompts must be a non-empty mapping"
            self._record_validation_error(error)
            return

        # `used_variables`：当前文件所有 Prompt 文本中真实使用到的变量集合。
        used_variables = self._collect_prompt_variables(prompts)
        declared_variables = set(input_variables)
        missing_variables = sorted(used_variables - declared_variables)
        if missing_variables:
            self._record_validation_error(
                f"{prompt_file}: input_variables missing {', '.join(missing_variables)}"
            )
            return

        extra_variables = sorted(declared_variables - used_variables)
        if extra_variables:
            self._record_validation_error(
                f"{prompt_file}: input_variables declared but unused {', '.join(extra_variables)}"
            )
            return

        # 在写入缓存前先检查是否存在跨文件重复 key，禁止覆盖式加载。
        duplicate_keys = sorted(
            prompt_key
            for prompt_key in prompts.keys()
            if prompt_key in (self._prompts.get(agent_type) or {})
        )
        if duplicate_keys:
            duplicate_sources = ", ".join(
                f"{prompt_key} -> {self._prompt_sources[agent_type][prompt_key]}"
                for prompt_key in duplicate_keys
            )
            self._record_validation_error(
                f"{prompt_file}: duplicate prompt keys detected for agent '{agent_type}': {duplicate_sources}"
            )
            return

        # 核心逻辑：Prompt 正文按 agent_type 聚合，便于通过 `agent.key` 方式统一读取。
        self._prompts.setdefault(agent_type, {}).update(prompts)
        self._prompt_sources.setdefault(agent_type, {}).update(
            {prompt_key: prompt_file for prompt_key in prompts.keys()}
        )
        # 元信息单独缓存，避免与正文混在一起，便于后续查询版本、模型适用范围、变更记录等信息。
        self._metadata.setdefault(agent_type, {})[scene] = {
            key: value
            for key, value in prompt_data.items()
            if key != "prompts"
        }
        logger.info("Loaded versioned prompts for agent=%s scene=%s", agent_type, scene)

    def _collect_prompt_variables(self, prompt_value: Any) -> set[str]:
        """递归提取 Prompt 文本中使用的变量名。"""
        collected_variables: set[str] = set()
        if isinstance(prompt_value, str):
            collected_variables.update(self.PROMPT_VARIABLE_PATTERN.findall(prompt_value))
            return collected_variables
        if isinstance(prompt_value, dict):
            for nested_value in prompt_value.values():
                collected_variables.update(self._collect_prompt_variables(nested_value))
        elif isinstance(prompt_value, list):
            for nested_value in prompt_value:
                collected_variables.update(self._collect_prompt_variables(nested_value))
        return collected_variables

    def _normalize_prompt_reference(self, prompt_key: str) -> str:
        """把完整 Prompt 引用归一化为 `agent.top_level_key` 形式。"""
        normalized_key = str(prompt_key or "").rstrip(".")
        segments = normalized_key.split(".")
        if len(segments) < 2:
            return normalized_key
        return f"{segments[0]}.{segments[1]}"

    def _infer_agent_scope_from_file(self, file_path: Path) -> str | None:
        """根据文件路径推断 `_get_prompt()` 的 Agent 命名空间。"""
        normalized_parts = [part.lower() for part in file_path.parts]
        if "agents" in normalized_parts:
            agent_index = normalized_parts.index("agents") + 1
            if agent_index < len(normalized_parts):
                candidate_scope = normalized_parts[agent_index]
                if candidate_scope in {"router", "retrieval", "generation", "file_processor", "tool", "planner", "critic"}:
                    return candidate_scope
        if "tools" in normalized_parts:
            return "tool"
        return None

    def _find_referenced_prompt_keys(self) -> set[str]:
        """扫描代码中实际引用到的 Prompt key。"""
        if self.project_root is None:
            return set()

        backend_dir = self.project_root / "backend"
        if not backend_dir.exists():
            return set()

        referenced_keys: set[str] = set()
        for python_file in backend_dir.rglob("*.py"):
            try:
                file_text = python_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for match in self.FULL_PROMPT_KEY_PATTERN.finditer(file_text):
                referenced_keys.add(self._normalize_prompt_reference(match.group(1)))

            agent_scope = self._infer_agent_scope_from_file(python_file)
            if agent_scope is None:
                continue
            for match in self.LOCAL_PROMPT_CALL_PATTERN.finditer(file_text):
                local_key = str(match.group(1) or "")
                top_level_key = local_key.split(".", 1)[0]
                referenced_keys.add(f"{agent_scope}.{top_level_key}")
        return referenced_keys

    def _validate_unused_prompts(self) -> None:
        """检查是否存在未被业务代码引用的 Prompt。"""
        referenced_keys = self._find_referenced_prompt_keys()
        if not referenced_keys:
            return

        for agent_type, prompts in self._prompts.items():
            for prompt_key in prompts.keys():
                full_prompt_key = f"{agent_type}.{prompt_key}"
                if full_prompt_key in referenced_keys:
                    continue
                prompt_source = self._prompt_sources.get(agent_type, {}).get(prompt_key)
                self._record_validation_error(
                    f"{prompt_source}: unused prompt key {full_prompt_key}"
                )

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
            logger.error("Error rendering prompt %s: %s", prompt_key, error)
            raise ValueError(f"Failed to render prompt {prompt_key}: {error}") from error

    def get_system_prompt(self, agent_type: str) -> str:
        """读取某类 Agent 的系统 Prompt。"""
        # 统一按约定命名规则读取系统 Prompt。
        return self.get_prompt(f"{agent_type}.{agent_type}_system_prompt", "")

    def get_user_prompt_template(self, agent_type: str) -> str:
        """读取某类 Agent 的用户 Prompt 原文。"""
        # 统一按约定命名规则读取用户 Prompt 模板原文。
        return self.get_prompt(f"{agent_type}.{agent_type}_user_prompt", "")

    def _normalize_chat_role(self, role: str) -> str:
        """把项目内部 role 归一化为聊天消息角色。"""
        normalized_role = str(role or "user").lower()
        if normalized_role in {"assistant", "ai"}:
            return "assistant"
        if normalized_role == "system":
            return "system"
        if normalized_role == "tool":
            return "tool"
        return "user"

    def _deserialize_history_message(self, message: Dict[str, Any]) -> BaseMessage:
        """把历史消息恢复为真实聊天消息对象，保留 tool protocol 字段。"""
        role = self._normalize_chat_role(str(message.get("role", "user")))
        content = str(message.get("content", ""))
        if role == "system":
            return SystemMessage(content=content)
        if role == "assistant":
            raw_tool_calls = message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []
            normalized_tool_calls = []
            for tool_call in raw_tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                normalized_tool_calls.append(
                    {
                        "id": tool_call.get("id"),
                        "type": "tool_call",
                        "name": tool_call.get("name"),
                        "args": tool_call.get("args") if isinstance(tool_call.get("args"), dict) else {},
                    }
                )
            if normalized_tool_calls:
                return AIMessage(content=content, tool_calls=normalized_tool_calls)
            return AIMessage(content=content)
        if role == "tool":
            tool_call_id = str(message.get("tool_call_id") or "")
            if tool_call_id:
                tool_name = message.get("name")
                status = "error" if str(message.get("status") or "success") == "error" else "success"
                return ToolMessage(
                    content=content,
                    tool_call_id=tool_call_id,
                    name=str(tool_name) if tool_name else None,
                    status=status,
                )
        return HumanMessage(content=content)

    def build_chat_prompt_call(
        self,
        *,
        user_prompt_key: str,
        user_variables: Dict[str, Any],
        conversation_history: List[Dict[str, Any]] | None = None,
        system_prompt_key: str | None = None,
        user_prompt_default: str = "{question}",
        max_history_messages: int = 10,
    ) -> tuple[ChatPromptTemplate, Dict[str, Any]]:
        """构造可直接调用的 `ChatPromptTemplate` 与变量映射。

        关键点：
        - 保留系统 Prompt 与用户 Prompt 的集中管理
        - 对话历史以真实消息形式进入模板，而不是先字符串化
        - 不再为旧版 `{conversation_history}` 占位符注入兼容变量
        """
        template_messages: List[Any] = []
        prompt_variables: Dict[str, Any] = dict(user_variables)

        if system_prompt_key:
            system_prompt = self.get_prompt(system_prompt_key, "")
            if system_prompt:
                template_messages.append(("system", system_prompt))

        recent_history = conversation_history[-max_history_messages:] if conversation_history and len(conversation_history) > max_history_messages else (conversation_history or [])
        for message in recent_history:
            # 中文说明：历史消息必须保留原始角色和 tool protocol 字段，
            # 否则 ToolAgent 二轮推理时会失去上下文闭环。
            template_messages.append(self._deserialize_history_message(message))

        user_prompt = self.get_prompt(user_prompt_key, user_prompt_default)
        template_messages.append(("user", user_prompt or user_prompt_default))
        return ChatPromptTemplate.from_messages(template_messages), prompt_variables

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
        _prompt_manager = PromptManager(strict=True)
    return _prompt_manager

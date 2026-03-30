# -*- coding: utf-8 -*-


import json
from datetime import datetime
"""
生成 Agent 模块，负责结合检索上下文、工具结果与会话历史生成最终回答。
"""

from typing import AsyncGenerator, Optional, List, Dict, Any

from pydantic import BaseModel, ConfigDict, Field
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput, ExecutionStatus
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.generation.source_extractor import SourceExtractor
from backend.agents.generation.hallucination_checker import HallucinationChecker
from backend.core.llm_manager import get_langchain_model_manager
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate


class AnswerQualityStructuredResult(BaseModel):
    """回答质量评估的结构化结果。"""

    model_config = ConfigDict(extra="allow")

    overall_score: float = 0.0
    relevance_score: Optional[float] = None
    completeness_score: Optional[float] = None
    clarity_score: Optional[float] = None
    grounded_score: Optional[float] = None
    reasoning: str = ""
    error: Optional[str] = None


class GenerationAgent(BaseAgent):
    """
    生成 Agent，负责调用模型生成答案，并可选执行引用提取与幻觉检查。
    """
    def __init__(self):
        """
        初始化生成 Agent，并准备 LLM 客户端、执行记录仓储、引用提取器和幻觉检查器。
        """
        super().__init__(
            agent_name="generation_agent",
            agent_type="generation"
        )

        # 初始化 LLM 客户端，后续所有回答生成都通过该客户端调用模型。
        self.model_manager = get_langchain_model_manager()

        # 初始化执行记录仓储，用于落库每次 Agent 执行的输入、输出与状态。
        self.execution_repo = get_agent_execution_repository()

        # 引用提取器用于从回答中解析引用标记及来源列表。
        self.source_extractor = SourceExtractor()
        # 幻觉检查器用于在需要时对生成答案做事后一致性评估。
        self.hallucination_checker = HallucinationChecker()

        self.enable_citation = self._get_config_value("enable_citation", True)
        self.enable_hallucination_check = self._get_config_value("enable_hallucination_check", True)
        self.max_context_length = self._get_config_value("max_context_length", 4000)

        logger = self.logger
        logger.info(f"Generation agent initialized (citation={self.enable_citation}, hallucination_check={self.enable_hallucination_check})")

    @staticmethod
    def _resolve_conversation_history(agent_input: AgentInput) -> List[Dict[str, Any]]:
        """Resolve conversation history from the canonical field first."""
        history = agent_input.get_conversation_history()
        if history:
            return history

        metadata = getattr(agent_input, "metadata", None)
        fallback_history = metadata.get("conversation_history") if isinstance(metadata, dict) else None
        return fallback_history if isinstance(fallback_history, list) else []

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        执行非流式生成流程，根据上下文类型选择不同的回答路径。
        """
        try:
            if agent_input.metadata:
                tool_result = agent_input.metadata.get("tool_result")
                retrieval_results = agent_input.metadata.get("retrieval_results")

                # 同时存在检索结果和工具结果时，优先走组合上下文生成路径。
                if tool_result and retrieval_results:
                    return await self.generate_with_combined_context(
                        agent_input,
                        retrieval_results=retrieval_results,
                        tool_result=tool_result,
                    )

                if tool_result:
                    return await self.generate_with_tool_result(agent_input, tool_result)

                if retrieval_results:
                    return await self.generate_with_context(agent_input, retrieval_results)

            # 若上游未提供检索或工具上下文，则走专门的直答 Prompt。
            prompt_template, prompt_variables = self._build_plain_response_prompt_call(
                user_content=agent_input.content,
                conversation_history=self._resolve_conversation_history(agent_input),
            )

            response = await self.model_manager.invoke_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000),
            )

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": response},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            output = self._create_output(
                content=response,
                status="success",
                execution_id=execution.execution_id
            )

            return output

        except Exception as e:
            self.logger.error(f"Generation agent execution failed: {str(e)}")

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e)
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_id=execution.execution_id
            )

    async def execute_stream(self, agent_input: AgentInput) -> AsyncGenerator[StreamChunk, None]:
        """
        执行流式生成流程，在不同阶段持续产出进度、内容与异常事件。
        """
        try:
            if agent_input.metadata:
                tool_result = agent_input.metadata.get("tool_result")
                retrieval_results = agent_input.metadata.get("retrieval_results")

                # 同时存在检索结果和工具结果时，优先走组合上下文生成路径。
                if tool_result and retrieval_results:
                    async for chunk in self.generate_with_combined_context_stream(
                        agent_input,
                        retrieval_results=retrieval_results,
                        tool_result=tool_result,
                    ):
                        yield chunk
                    return

                if tool_result:
                    async for chunk in self.generate_with_tool_result_stream(agent_input, tool_result):
                        yield chunk
                    return

                if retrieval_results:
                    async for chunk in self.generate_with_context_stream(agent_input, retrieval_results):
                        yield chunk
                    return

            yield StreamChunk.create_thinking("正在生成回答...")

            # 若上游未提供检索或工具上下文，则走专门的直答 Prompt。
            prompt_template, prompt_variables = self._build_plain_response_prompt_call(
                user_content=agent_input.content,
                conversation_history=self._resolve_conversation_history(agent_input)
            )

            full_content = ""
            async for chunk in self.model_manager.stream_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": full_content},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            yield StreamChunk.create_result({
                "execution_id": execution.execution_id,
                "content_length": len(full_content)
            })

        except Exception as e:
            self.logger.error(f"Generation agent stream execution failed: {str(e)}")

            self.execution_repo.create_execution_with_result(
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content},
                output_data={},
                status="failed",
                execution_time_ms=0,
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                error_message=str(e)
            )

            yield StreamChunk.create_error(str(e))

    async def generate_with_context(
        self,
        agent_input: AgentInput,
        retrieval_results: list
    ) -> AgentOutput:
        """
        基于检索上下文生成非流式回答。
        """
        try:
            context = self._format_retrieval_context(retrieval_results)

            prompt_template, prompt_variables = self._build_messages_with_context(
                user_content=agent_input.content,
                context=context,
                conversation_history=self._resolve_conversation_history(agent_input)
            )

            response = await self.model_manager.invoke_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000),
            )

            citations = self._extract_citations(response, retrieval_results)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content, "context": context}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": response, "citations": citations},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            output = self._create_output(
                content=response,
                status="success",
                execution_id=execution.execution_id,
                citations=citations
            )

            return output

        except Exception as e:
            self.logger.error(f"Generation with context failed: {str(e)}")

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e)
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_id=execution.execution_id
            )

    async def generate_with_context_stream(
        self,
        agent_input: AgentInput,
        retrieval_results: list
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        基于检索上下文生成流式回答。
        """
        try:
            yield StreamChunk.create_thinking("正在基于检索结果生成回答")

            context = self._format_retrieval_context(retrieval_results)

            prompt_template, prompt_variables = self._build_messages_with_context(
                user_content=agent_input.content,
                context=context,
                conversation_history=self._resolve_conversation_history(agent_input)
            )

            full_content = ""
            async for chunk in self.model_manager.stream_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

            citations = self._extract_citations(full_content, retrieval_results)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content, "context": context}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": full_content, "citations": citations},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            yield StreamChunk.create_result({
                "execution_id": execution.execution_id,
                "content_length": len(full_content),
                "citations": citations
            })

        except Exception as e:
            self.logger.error(f"Generation with context stream failed: {str(e)}")

            self.execution_repo.create_execution_with_result(
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content},
                output_data={},
                status="failed",
                execution_time_ms=0,
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                error_message=str(e)
            )

            yield StreamChunk.create_error(str(e))

    async def generate_with_combined_context(
        self,
        agent_input: AgentInput,
        retrieval_results: list,
        tool_result: dict,
    ) -> AgentOutput:
        """
        结合检索结果与工具结果生成非流式回答。
        """
        try:
            combined_context = self._format_combined_context(retrieval_results, tool_result)
            prompt_template, prompt_variables = self._build_messages_with_context(
                user_content=agent_input.content,
                context=combined_context,
                conversation_history=self._resolve_conversation_history(agent_input),
            )

            response = await self.model_manager.invoke_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000),
            )
            citations = self._extract_citations(response, retrieval_results)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={
                    "content": agent_input.content,
                    "retrieval_results": retrieval_results,
                    "tool_result": tool_result,
                },
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": response, "citations": citations},
                status="success",
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content=response,
                status="success",
                execution_id=execution.execution_id,
                citations=citations,
                tool_result=tool_result,
            )

        except Exception as e:
            self.logger.error(f"Generation with combined context failed: {str(e)}")

            self.execution_repo.create_execution_with_result(
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content},
                output_data={},
                status="failed",
                execution_time_ms=0,
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                error_message=str(e),
            )

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
            )

    async def generate_with_combined_context_stream(
        self,
        agent_input: AgentInput,
        retrieval_results: list,
        tool_result: dict,
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        结合检索结果与工具结果生成流式回答。
        """
        try:
            yield StreamChunk.create_thinking("正在综合检索结果和工具结果生成回答...")

            combined_context = self._format_combined_context(retrieval_results, tool_result)
            prompt_template, prompt_variables = self._build_messages_with_context(
                user_content=agent_input.content,
                context=combined_context,
                conversation_history=self._resolve_conversation_history(agent_input),
            )

            full_content = ""
            async for chunk in self.model_manager.stream_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000),
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

            citations = self._extract_citations(full_content, retrieval_results)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={
                    "content": agent_input.content,
                    "retrieval_results": retrieval_results,
                    "tool_result": tool_result,
                },
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": full_content, "citations": citations},
                status="success",
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            yield StreamChunk.create_result(
                {
                    "execution_id": execution.execution_id,
                    "content_length": len(full_content),
                    "citations": citations,
                    "tool_result": tool_result,
                }
            )

        except Exception as e:
            self.logger.error(f"Generation with combined context stream failed: {str(e)}")

            self.execution_repo.create_execution_with_result(
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content},
                output_data={},
                status="failed",
                execution_time_ms=0,
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                error_message=str(e),
            )

            yield StreamChunk.create_error(str(e))

    def _format_retrieval_context(self, retrieval_results: list) -> str:
        """
        将检索结果格式化为可直接提供给模型的上下文字符串。
        """
        if not retrieval_results:
            return ""

        context_parts = []
        for i, result in enumerate(retrieval_results, start=1):
            context_part = self._get_prompt(
                "context_format",
                index=i,
                source_name=result.get("metadata", {}).get("source", "Unknown"),
                relevance_score=f"{result.get('score', 0):.2f}",
                content=result.get("content", ""),
            )

            context_parts.append(context_part)

        return "\n\n".join(context_parts)

    def _build_plain_response_prompt_call(
        self,
        user_content: str,
        conversation_history: list | None = None,
    ) -> tuple:
        """构建无外部上下文时的普通回答 Prompt 调用参数。"""
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key="generation.generation_plain_response_prompt",
            user_variables={
                "question": user_content,
            },
            conversation_history=conversation_history,
            system_prompt_key="generation.generation_plain_response_system_prompt",
        )

    def _extract_citations(self, content: str, retrieval_results: list) -> list:
        """
        从生成内容中提取引用编号，并映射为结构化来源信息。
        """
        if not self.enable_citation:
            return []

        return self.source_extractor.extract_citations(content, retrieval_results)

    async def check_hallucination(
        self,
        question: str,
        context: str,
        answer: str,
        retrieval_results: Optional[List[Dict[str, Any]]] = None
    ) -> dict:
        """
        对生成答案执行幻觉检查，评估内容是否与检索上下文保持一致。
        """
        if not self.enable_hallucination_check:
            return {"has_hallucination": False, "confidence": 1.0, "reason": "Hallucination check disabled"}

        if retrieval_results:
            return await self.hallucination_checker.check_hallucination(
                generated_content=answer,
                retrieval_results=retrieval_results,
                user_question=question
            )
        else:
            is_valid = self.hallucination_checker.quick_check(answer, [])
            return {
                "has_hallucination": not is_valid,
                "confidence": 0.7 if is_valid else 0.3,
                "reason": "Quick check only (no retrieval results provided)"
            }

    async def evaluate_answer_quality(
        self,
        question: str,
        answer: str
    ) -> dict:
        """
        评估回答质量，并返回结构化评分结果。
        """
        try:
            prompt_template, prompt_variables = self.prompt_manager.build_chat_prompt_call(
                user_prompt_key="generation.answer_quality_prompt",
                user_variables={
                    "question": question,
                    "answer": answer,
                    "conversation_history": "",
                },
            )
            result_model = await self.model_manager.with_structured_output(
                AnswerQualityStructuredResult
            ).invoke_chat_prompt_template(
                prompt_template,
                prompt_variables,
                temperature=0.3,
                max_tokens=500,
            )
            return result_model.model_dump()
        except Exception as e:
            self.logger.error(f"Answer quality evaluation failed: {str(e)}")
            return {"overall_score": 0.0, "error": str(e)}

    def _build_messages_with_context(
        self,
        user_content: str,
        context: str,
        conversation_history: list = None
    ) -> tuple:
        """
        构建带检索上下文的 ChatPromptTemplate 调用参数。
        """
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key="generation.generation_with_context_prompt",
            user_variables={
                "question": user_content,
                "context": context,
            },
            conversation_history=conversation_history,
            system_prompt_key="generation.generation_system_prompt",
        )

    async def generate_with_tool_result(
        self,
        agent_input: AgentInput,
        tool_result: dict
    ) -> AgentOutput:
        """
        基于工具调用结果生成非流式回答。
        """
        try:
            tool_context = self._format_tool_result_context(tool_result)

            prompt_template, prompt_variables = self._build_messages_with_tool_result(
                user_content=agent_input.content,
                tool_context=tool_context,
                conversation_history=self._resolve_conversation_history(agent_input)
            )

            response = await self.model_manager.invoke_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000),
            )

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content, "tool_result": tool_result}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": response},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            output = self._create_output(
                content=response,
                status="success",
                execution_id=execution.execution_id,
                tool_result=tool_result
            )

            return output

        except Exception as e:
            self.logger.error(f"Generation with tool result failed: {str(e)}")

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={},
                status="failed",
                error_message=str(e)
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            return self._create_output(
                content="",
                status="failed",
                error_message=str(e),
                execution_id=execution.execution_id
            )

    async def generate_with_tool_result_stream(
        self,
        agent_input: AgentInput,
        tool_result: dict
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        基于工具调用结果生成流式回答。
        """
        try:
            yield StreamChunk.create_thinking("正在基于工具结果生成回答...")

            tool_context = self._format_tool_result_context(tool_result)

            prompt_template, prompt_variables = self._build_messages_with_tool_result(
                user_content=agent_input.content,
                tool_context=tool_context,
                conversation_history=self._resolve_conversation_history(agent_input)
            )

            full_content = ""
            async for chunk in self.model_manager.stream_chat_prompt_template(
                prompt_template=prompt_template,
                prompt_variables=prompt_variables,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

            # 先创建执行记录，便于后续关联输出内容和执行状态。
            execution_create = AgentExecutionCreate(
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content, "tool_result": tool_result}
            )
            execution = self.execution_repo.create_execution(execution_create)

            execution_update = AgentExecutionUpdate(
                output_data={"content": full_content},
                status="success"
            )
            self.execution_repo.update_execution(execution.execution_id, execution_update)

            yield StreamChunk.create_result({
                "execution_id": execution.execution_id,
                "content_length": len(full_content),
                "tool_result": tool_result
            })

        except Exception as e:
            self.logger.error(f"Generation with tool result stream failed: {str(e)}")

            self.execution_repo.create_execution_with_result(
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                input_data={"content": agent_input.content},
                output_data={},
                status="failed",
                execution_time_ms=0,
                conversation_id=agent_input.conversation_id,
                message_id=agent_input.message_id,
                error_message=str(e)
            )

            yield StreamChunk.create_error(str(e))

    def _format_tool_result_context(self, tool_result: dict) -> str:
        """
        将工具结果格式化为模型可用的上下文文本。
        """
        if not tool_result:
            return ""

        tool_results = tool_result.get("tool_results") if isinstance(tool_result.get("tool_results"), list) else None
        if tool_results:
            context_parts = []
            for index, tool_item in enumerate(tool_results, start=1):
                if not isinstance(tool_item, dict):
                    continue
                current_tool_name = tool_item.get("tool_name", f"Tool {index}")
                interpreted_result = tool_item.get("interpreted_result") or {}
                formatted_text = interpreted_result.get("formatted_text") or self._safe_stringify(tool_item.get("tool_result"))
                context_parts.append(f"工具 {index}：{current_tool_name}\n工具返回结果：\n{formatted_text}")
            if context_parts:
                return "\n\n".join(context_parts)

        tool_name = tool_result.get("tool_name", "Unknown")
        interpreted_result = tool_result.get("interpreted_result", {})
        formatted_text = interpreted_result.get("formatted_text", "")
        if not formatted_text:
            formatted_text = self._safe_stringify(tool_result.get("tool_result"))

        context = f"工具名称：{tool_name}\n"
        context += f"工具返回结果：\n{formatted_text}\n"

        return context

    @staticmethod
    def _safe_stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def _format_combined_context(self, retrieval_results: list, tool_result: dict) -> str:
        """
        将检索结果与工具结果组装为统一的上下文输入。
        """
        retrieval_context = self._format_retrieval_context(retrieval_results)
        tool_context = self._format_tool_result_context(tool_result)

        context_parts = []
        if tool_context:
            context_parts.append(f"工具结果：\n{tool_context}")
        if retrieval_context:
            context_parts.append(f"检索上下文：\n{retrieval_context}")
        return "\n\n".join(context_parts)

    def _build_messages_with_tool_result(
        self,
        user_content: str,
        tool_context: str,
        conversation_history: list = None
    ) -> tuple:
        """
        构建包含工具结果的 ChatPromptTemplate 调用参数。
        """
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key="generation.generation_user_prompt_with_tool_result",
            user_variables={
                "question": user_content,
                "tool_context": tool_context,
            },
            conversation_history=conversation_history,
            system_prompt_key="generation.generation_system_prompt_with_tool_result",
        )

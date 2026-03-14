"""
生成智能体，负责基于用户问题生成回答。
"""

from datetime import datetime
from typing import AsyncGenerator, Optional, List, Dict, Any
from backend.agents.base.base_agent import BaseAgent
from backend.agents.base.agent_input import AgentInput
from backend.agents.base.agent_output import AgentOutput, ExecutionStatus
from backend.agents.base.stream_chunk import StreamChunk
from backend.agents.generation.source_extractor import SourceExtractor
from backend.agents.generation.hallucination_checker import HallucinationChecker
from backend.utils.llm_client import get_llm_client
from backend.database.repositories.agent_execution_repository import get_agent_execution_repository
from backend.models.agent_execution import AgentExecutionCreate, AgentExecutionUpdate


class GenerationAgent(BaseAgent):
    """
    生成智能体。
    功能：
    1. 基于用户问题生成回答
    2. 支持流式输出
    3. 保存生成记录
    4. 引用来源提取
    5. 幻觉检测
    第一阶段：不考虑检索上下文，直接基于问题生成回答。
    """

    def __init__(self):
        """初始化生成智能体"""
        super().__init__(
            agent_name="generation_agent",
            agent_type="generation"
        )

        self.llm_client = get_llm_client()

        self.execution_repo = get_agent_execution_repository()

        self.source_extractor = SourceExtractor()
        self.hallucination_checker = HallucinationChecker()

        self.enable_citation = self._get_config_value("enable_citation", True)
        self.enable_hallucination_check = self._get_config_value("enable_hallucination_check", True)
        self.max_context_length = self._get_config_value("max_context_length", 4000)

        logger = self.logger
        logger.info(f"Generation agent initialized (citation={self.enable_citation}, hallucination_check={self.enable_hallucination_check})")

    async def execute(self, agent_input: AgentInput) -> AgentOutput:
        """
        执行生成任务（非流式）
        Args:
            agent_input: 智能体输入
        Returns:
            智能体输出，包含生成的回答
        """
        try:
            if agent_input.metadata:
                tool_result = agent_input.metadata.get("tool_result")
                retrieval_results = agent_input.metadata.get("retrieval_results")

                if tool_result:
                    return await self.generate_with_tool_result(agent_input, tool_result)

                if retrieval_results:
                    return await self.generate_with_context(agent_input, retrieval_results)

            messages = self._build_messages(
                user_content=agent_input.content,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            )

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
        执行生成任务（流式）

        Args:
            agent_input: 智能体输入
        Yields:
            流式数据
        """
        try:
            if agent_input.metadata:
                tool_result = agent_input.metadata.get("tool_result")
                retrieval_results = agent_input.metadata.get("retrieval_results")

                if tool_result:
                    async for chunk in self.generate_with_tool_result_stream(agent_input, tool_result):
                        yield chunk
                    return

                if retrieval_results:
                    async for chunk in self.generate_with_context_stream(agent_input, retrieval_results):
                        yield chunk
                    return

            yield StreamChunk.create_thinking("正在生成回答...")

            messages = self._build_messages(
                user_content=agent_input.content,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            full_content = ""
            async for chunk in self.llm_client.chat_completion_stream(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

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
        基于检索结果生成回答（用于第二阶段 RAG）
        Args:
            agent_input: 智能体输入
            retrieval_results: 检索结果列表
        Returns:
            智能体输出
        """
        try:
            context = self._format_retrieval_context(retrieval_results)

            messages = self._build_messages_with_context(
                user_content=agent_input.content,
                context=context,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            )

            citations = self._extract_citations(response, retrieval_results)

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
        基于检索结果流式生成回答（用于第二阶段 RAG）
        Args:
            agent_input: 智能体输入
            retrieval_results: 检索结果列表
        Yields:
            流式数据
        """
        try:
            yield StreamChunk.create_thinking("正在基于检索结果生成回答")

            context = self._format_retrieval_context(retrieval_results)

            messages = self._build_messages_with_context(
                user_content=agent_input.content,
                context=context,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            full_content = ""
            async for chunk in self.llm_client.chat_completion_stream(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

            citations = self._extract_citations(full_content, retrieval_results)

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

    def _format_retrieval_context(self, retrieval_results: list) -> str:
        """
        格式化检索结果为上下文字符串

        Args:
            retrieval_results: 检索结果列表
        Returns:
            格式化后的上下文字符串
        """
        if not retrieval_results:
            return ""

        context_parts = []
        for i, result in enumerate(retrieval_results, start=1):
            context_format = self._get_prompt("context_format")
            if context_format:
                context_part = context_format.format(
                    index=i,
                    source_name=result.get("metadata", {}).get("source", "Unknown"),
                    relevance_score=f"{result.get('score', 0):.2f}",
                    content=result.get("content", "")
                )
            else:
                context_part = f"[{i}] 来源：{result.get('metadata', {}).get('source', 'Unknown')}\n"
                context_part += f"相关度：{result.get('score', 0):.2f}\n"
                context_part += f"内容：{result.get('content', '')}\n"

            context_parts.append(context_part)

        return "\n\n".join(context_parts)

    def _extract_citations(self, content: str, retrieval_results: list) -> list:
        """
        从生成的内容中提取引用信息（使用 SourceExtractor）
        Args:
            content: 生成的内容
            retrieval_results: 检索结果列表
        Returns:
            引用列表
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
        检查生成的回答是否包含幻觉（使用 HallucinationChecker）
        Args:
            question: 用户问题
            context: 提供的上下文
            answer: 生成的回答
            retrieval_results: 检索结果列表（可选）

        Returns:
            幻觉检查结果字典
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
        评估回答质量

        Args:
            question: 用户问题
            answer: 生成的回答
        Returns:
            质量评估结果字典
        """
        try:
            eval_prompt = self._get_prompt(
                "answer_quality_prompt",
                question=question,
                answer=answer
            )

            if not eval_prompt:
                self.logger.warning("Answer quality prompt not found")
                return {"overall_score": 0.0}

            messages = [{"role": "user", "content": eval_prompt}]
            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=500
            )

            import json
            import re

            try:
                # 尝试提取JSON内容（处理LLM可能返回的额外文本）
                json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_match = re.search(r'\{.*\}', response, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)
                    else:
                        json_str = response

                result = json.loads(json_str)
                return result
            except json.JSONDecodeError as e:
                self.logger.warning(f"JSON 解析失败: {e}，返回默认评分")
                return {"overall_score": 0.0, "error": "JSON解析失败"}

        except Exception as e:
            self.logger.error(f"Answer quality evaluation failed: {str(e)}")
            return {"overall_score": 0.0, "error": str(e)}

    def _build_messages_with_context(
        self,
        user_content: str,
        context: str,
        conversation_history: list = None
    ) -> list:
        """
        构建包含上下文的消息列表

        Args:
            user_content: 用户输入内容
            context: 检索上下文
            conversation_history: 对话历史

        Returns:
            消息列表
        """
        messages = []

        system_prompt = self._get_prompt("generation_system_prompt")
        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        history_str = ""
        if conversation_history:
            history_str = self.prompt_manager.format_conversation_history(
                conversation_history,
                prompt_type=self.agent_type
            )

        user_prompt = self._get_prompt(
            "generation_with_context_prompt",
            question=user_content,
            context=context,
            conversation_history=history_str
        )

        if user_prompt:
            messages.append({
                "role": "user",
                "content": user_prompt
            })
        else:
            messages.append({
                "role": "user",
                "content": f"参考以下上下文回答问题：\n\n上下文：\n{context}\n\n问题：{user_content}"
            })

        return messages

    async def generate_with_tool_result(
        self,
        agent_input: AgentInput,
        tool_result: dict
    ) -> AgentOutput:
        """
        基于工具调用结果生成回答（用于第三阶段工具调用）

        Args:
            agent_input: 智能体输入
            tool_result: 工具调用结果

        Returns:
            智能体输出
        """
        try:
            tool_context = self._format_tool_result_context(tool_result)

            messages = self._build_messages_with_tool_result(
                user_content=agent_input.content,
                tool_context=tool_context,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            )

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
        基于工具调用结果流式生成回答（用于第三阶段工具调用）

        Args:
            agent_input: 智能体输入
            tool_result: 工具调用结果

        Yields:
            流式数据
        """
        try:
            yield StreamChunk.create_thinking("正在基于工具结果生成回答...")

            tool_context = self._format_tool_result_context(tool_result)

            messages = self._build_messages_with_tool_result(
                user_content=agent_input.content,
                tool_context=tool_context,
                conversation_history=agent_input.metadata.get("conversation_history", []) if agent_input.metadata else []
            )

            full_content = ""
            async for chunk in self.llm_client.chat_completion_stream(
                messages=messages,
                temperature=self._get_config_value("temperature", 0.7),
                max_tokens=self._get_config_value("max_tokens", 2000)
            ):
                full_content += chunk
                yield StreamChunk.create_content(chunk)

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
        格式化工具结果为上下文字符串

        Args:
            tool_result: 工具调用结果

        Returns:
            格式化后的上下文字符串
        """
        if not tool_result:
            return ""

        tool_name = tool_result.get("tool_name", "Unknown")
        interpreted_result = tool_result.get("interpreted_result", {})
        formatted_text = interpreted_result.get("formatted_text", "")

        context = f"工具名称：{tool_name}\n"
        context += f"工具返回结果：\n{formatted_text}\n"

        return context

    def _build_messages_with_tool_result(
        self,
        user_content: str,
        tool_context: str,
        conversation_history: list = None
    ) -> list:
        """
        构建包含工具结果的消息列表
        Args:
            user_content: 用户输入内容
            tool_context: 工具结果上下文
            conversation_history: 对话历史

        Returns:
            消息列表
        """
        messages = []

        system_prompt = self._get_prompt("generation_system_prompt_with_tool_result")
        if not system_prompt:
            system_prompt = self._get_prompt("generation_system_prompt")

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        history_str = ""
        if conversation_history:
            history_str = self.prompt_manager.format_conversation_history(
                conversation_history,
                prompt_type=self.agent_type
            )

        user_prompt = self._get_prompt(
            "generation_user_prompt_with_tool_result",
            question=user_content,
            tool_context=tool_context,
            conversation_history=history_str
        )

        if user_prompt:
            messages.append({
                "role": "user",
                "content": user_prompt
            })
        else:
            messages.append({
                "role": "user",
                "content": f"参考以下工具调用结果回答问题：\n\n工具结果：\n{tool_context}\n\n问题：{user_content}"
            })

        return messages

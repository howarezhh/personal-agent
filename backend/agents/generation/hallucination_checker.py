# -*- coding: utf-8 -*-


from typing import List, Dict, Any, Optional
"""
幻觉检查模块，负责评估生成答案与检索上下文之间的一致性与风险。
"""

from backend.utils.logger import get_logger
from backend.core.llm_manager import get_langchain_model_manager
from backend.core.prompt_manager import get_prompt_manager
from pydantic import BaseModel, Field


class HallucinationCheckStructuredResult(BaseModel):
    """Structured result for hallucination checks."""

    has_hallucination: bool = False
    consistency_score: float = 0.5
    hallucination_points: List[str] = Field(default_factory=list)
    reasoning: str = ""


class HallucinationChecker:
    """
    幻觉检查器，通过规则方法与大模型评估相结合的方式判断答案风险。
    """
    def __init__(self):
        """
        初始化幻觉检查器，准备 LLM 客户端、风险阈值和规则检查所需的基础配置。
        """
        self.logger = get_logger(self.__class__.__name__)
        # 初始化 LLM 客户端，在规则检查不足时用于执行更细粒度的一致性评估。
        self.model_manager = get_langchain_model_manager()
        self.prompt_manager = get_prompt_manager()

        # 幻觉检查的阈值
        self.consistency_threshold = 0.7  # 一致性分数阈值
        self.citation_coverage_threshold = 0.5  # 引用覆盖率阈值

    async def check_hallucination(
        self,
        generated_content: str,
        retrieval_results: List[Dict[str, Any]],
        user_question: str
    ) -> Dict[str, Any]:
        """
        执行完整的幻觉检查流程，先做规则检查，再视情况调用 LLM 进行辅助评估。
        """
        if not generated_content or not retrieval_results:
            return {
                "has_hallucination": False,
                "consistency_score": 1.0,
                "reason": "No content or retrieval results to check"
            }

        try:
            # 1. 基于规则的快速检查
            rule_based_result = self._rule_based_check(generated_content, retrieval_results)

            # 2. 基于LLM的深度检查（可选，更准确但更慢）
            llm_based_result = await self._llm_based_check(
                generated_content,
                retrieval_results,
                user_question
            )

            # 3. 综合判断
            final_result = self._combine_results(rule_based_result, llm_based_result)

            self.logger.info(
                f"Hallucination check completed: "
                f"has_hallucination={final_result['has_hallucination']}, "
                f"consistency_score={final_result['consistency_score']:.2f}"
            )

            return final_result

        except Exception as e:
            self.logger.error(f"Error checking hallucination: {str(e)}", exc_info=True)
            return {
                "has_hallucination": False,
                "consistency_score": 0.5,
                "reason": f"Error during check: {str(e)}"
            }

    def _rule_based_check(
        self,
        generated_content: str,
        retrieval_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        基于规则快速检查生成内容是否存在明显超出上下文支撑的风险信号。
        """
        import re

        # 检查是否包含引用标记
        citation_pattern = r'\[(\d+)\]'
        citations = re.findall(citation_pattern, generated_content)
        has_citations = len(citations) > 0

        # 计算引用覆盖率
        citation_coverage = len(citations) / len(retrieval_results) if retrieval_results else 0

        # 检查是否包含明显的幻觉关键词
        hallucination_keywords = [
            "我认为", "我觉得", "可能是", "大概是", "应该是",
            "据我所知", "根据我的理解", "我猜测"
        ]
        has_hallucination_keywords = any(
            keyword in generated_content for keyword in hallucination_keywords
        )

        # 计算一致性分数
        consistency_score = 1.0
        if not has_citations:
            consistency_score -= 0.3
        if citation_coverage < self.citation_coverage_threshold:
            consistency_score -= 0.2
        if has_hallucination_keywords:
            consistency_score -= 0.2

        consistency_score = max(0.0, consistency_score)

        return {
            "has_citations": has_citations,
            "citation_count": len(citations),
            "citation_coverage": citation_coverage,
            "has_hallucination_keywords": has_hallucination_keywords,
            "consistency_score": consistency_score,
            "check_type": "rule_based"
        }

    async def _llm_based_check(
        self,
        generated_content: str,
        retrieval_results: List[Dict[str, Any]],
        user_question: str
    ) -> Dict[str, Any]:
        """
        检查生成内容是否与检索上下文一致，并返回结构化判定结果。
        """
        try:
            context = self._format_retrieval_context(retrieval_results)
            prompt_template, prompt_variables = self._build_check_prompt_call(
                user_question=user_question,
                context=context,
                generated_content=generated_content,
            )
            result_model = await self.model_manager.with_structured_output(
                HallucinationCheckStructuredResult
            ).invoke_chat_prompt_template(
                prompt_template,
                prompt_variables,
                temperature=0.1,
                max_tokens=500,
            )

            result = result_model.model_dump()
            result["check_type"] = "llm_based"
            return result

        except Exception as e:
            self.logger.error(f"LLM-based check failed: {str(e)}", exc_info=True)
            return {
                "has_hallucination": False,
                "consistency_score": 0.5,
                "check_type": "llm_based",
                "error": str(e)
            }

    def _build_check_prompt_call(
        self,
        *,
        user_question: str,
        context: str,
        generated_content: str,
    ):
        """构造用于幻觉检查的 ChatPromptTemplate 调用参数。"""
        check_prompt_key = "generation.hallucination_check_prompt"
        system_prompt_key = "generation.hallucination_check_system_prompt"
        if not self.prompt_manager.get_prompt(check_prompt_key):
            raise ValueError(f"{check_prompt_key} is not configured")
        if not self.prompt_manager.get_prompt(system_prompt_key):
            raise ValueError(f"{system_prompt_key} is not configured")
        return self.prompt_manager.build_chat_prompt_call(
            user_prompt_key=check_prompt_key,
            user_variables={
                "question": user_question,
                "context": context,
                "answer": generated_content,
            },
            system_prompt_key=system_prompt_key,
            user_prompt_default="{question}",
        )

    def _combine_results(
        self,
        rule_based_result: Dict[str, Any],
        llm_based_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        # 计算综合一致性分数（规则检查权重0.4，LLM检查权重0.6）
        """
        合并规则检查与 LLM 检查的结果，生成最终判定。
        """
        rule_score = rule_based_result.get("consistency_score", 0.5)
        llm_score = llm_based_result.get("consistency_score", 0.5)
        combined_score = rule_score * 0.4 + llm_score * 0.6

        # 判断是否存在幻觉
        has_hallucination = (
            combined_score < self.consistency_threshold or
            llm_based_result.get("has_hallucination", False)
        )

        result = {
            "has_hallucination": has_hallucination,
            "consistency_score": combined_score,
            "rule_based_score": rule_score,
            "llm_based_score": llm_score,
            "has_citations": rule_based_result.get("has_citations", False),
            "citation_count": rule_based_result.get("citation_count", 0),
            "citation_coverage": rule_based_result.get("citation_coverage", 0.0),
            "hallucination_points": llm_based_result.get("hallucination_points", []),
            "reasoning": llm_based_result.get("reasoning", ""),
            "recommendation": self._generate_recommendation(combined_score, has_hallucination)
        }

        return result

    def _generate_recommendation(
        self,
        consistency_score: float,
        has_hallucination: bool
    ) -> str:
        """
        根据幻觉风险级别生成处理建议。
        """
        if not has_hallucination and consistency_score >= 0.9:
            return "内容质量良好，与检索结果高度一致"
        elif not has_hallucination and consistency_score >= 0.7:
            return "内容基本可靠，建议增加更多引用标记"
        elif has_hallucination and consistency_score >= 0.5:
            return "检测到可能的幻觉内容，建议重新生成并严格基于检索结果"
        else:
            return "内容与检索结果一致性较低，强烈建议重新生成"

    def _format_retrieval_context(self, retrieval_results: List[Dict[str, Any]]) -> str:
        """
        将检索结果格式化为适合幻觉检查的上下文文本。
        """
        if not retrieval_results:
            return ""

        context_parts = []
        for i, result in enumerate(retrieval_results, start=1):
            context_part = f"[{i}] {result.get('content', '')}"
            context_parts.append(context_part)

        return "\n\n".join(context_parts)

    def quick_check(
        self,
        generated_content: str,
        retrieval_results: List[Dict[str, Any]]
    ) -> bool:
        """
        执行不依赖 LLM 的快速预检，便于在轻量场景下快速评估风险。
        """
        result = self._rule_based_check(generated_content, retrieval_results)
        return result["consistency_score"] >= self.consistency_threshold

# -*- coding: utf-8 -*-

"""
生成 Agent 对外导出模块，统一暴露生成相关的核心对象供注册表或上层调用。
"""

from backend.agents.generation.generation_agent import GenerationAgent
from backend.agents.generation.source_extractor import SourceExtractor
from backend.agents.generation.hallucination_checker import HallucinationChecker

__all__ = [
    "GenerationAgent",
    "SourceExtractor",
    "HallucinationChecker"
]

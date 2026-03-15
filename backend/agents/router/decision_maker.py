
from typing import Dict, Any, List, Optional
from backend.utils.logger import get_logger
from backend.tools.tool_registry import get_tool_registry
from backend.tools.tool_initializer import ensure_tools_initialized


class DecisionMaker:
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

        # 获取工具注册表（新增：工具感知能力）
        try:
            self.tool_registry = get_tool_registry()
            if self.tool_registry.get_tool_count() == 0:
                ensure_tools_initialized(strict=False)
                self.logger.info("工具注册表为空，已触发自动初始化")
            self._build_tool_category_map()
            self.logger.info(f"决策制定器初始化完成，可用工具数量: {self.tool_registry.get_tool_count()}")
        except Exception as e:
            self.logger.warning(f"工具注册表初始化失败: {str(e)}")
            self.tool_registry = None

        # 定义各类问题的关键词特征（增强版：按类型分组）
        self.action_keywords = {
            "direct_answer": {
                "greetings": ["你好", "您好", "hi", "hello", "嗨", "早上好", "晚上好"],
                "thanks": ["谢谢", "感谢", "多谢", "thanks"],
                "farewell": ["再见", "拜拜", "bye", "goodbye"],
                "simple_questions": ["什么是", "谁是", "为什么", "怎么样"],
                "common_sense": ["常识", "基础", "简单"]
            },
            "retrieval": {
                "query_intent": ["根据", "查询", "查找"],
                "document_related": ["文档", "资料", "知识库", "记录", "档案"],
                "detail_request": ["详细", "具体", "说明", "介绍", "解释"],
                "enterprise_info": ["企业", "公司", "产品", "政策", "规定", "流程"],
                "history_request": ["历史", "之前", "以前", "过去"]
            },
            "tool_call": {
                "calculation": ["计算", "算", "加", "减", "乘", "除", "等于"],
                "weather": ["天气", "气温", "温度", "下雨", "晴天"],
                "time": ["时间", "日期", "现在几点", "今天", "明天"],
                "translation": ["翻译", "英文", "中文", "日文"],
                "web_search": ["搜索", "最新", "新闻"],
                "generation": ["生成", "创建", "写", "制作"],
                "conversion": ["转换", "换算", "兑换"]
            }
        }

        # 问题长度阈值
        self.short_question_length = 10
        self.long_question_length = 50

        # 显式检索信号：只要用户明确限定“知识库/文档/资料”等范围，就优先走检索
        self.explicit_retrieval_keywords = [
            "知识库", "文档", "资料", "档案", "文件里", "文件中", "上传的文件",
            "库里", "库中", "内部资料", "内部文档", "检索结果", "向量库"
        ]
        self.explicit_retrieval_phrases = [
            "知识库里面", "知识库中", "在知识库里", "从知识库里",
            "文档里面", "文档中", "资料里面", "资料中", "从文档里"
        ]

        # 显式外部工具信号：只有非常明确需要联网/计算/翻译/天气等时才优先工具
        self.explicit_external_tool_keywords = [
            "联网", "互联网", "网页", "网站", "实时", "最新", "新闻", "搜索", "检索网页",
            "天气", "气温", "温度", "汇率", "兑换", "翻译", "计算", "算一下",
            "现在几点", "时间", "日期", "ip", "百科", "维基"
        ]

    def _build_tool_category_map(self):
        self.tool_category_map = {}
        if not self.tool_registry:
            return

        all_tools = self.tool_registry.get_all_tools()
        for tool_name, tool_instance in all_tools.items():
            definition = tool_instance.get_definition()
            category = definition.category

            if category not in self.tool_category_map:
                self.tool_category_map[category] = []
            self.tool_category_map[category].append({
                "name": tool_name,
                "description": definition.description
            })

        self.logger.debug(f"工具类别映射构建完成: {list(self.tool_category_map.keys())}")

    def analyze_question(
        self,
        question: str,
        conversation_history: Optional[List] = None,
        llm_decision: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not question:
            return {
                "action": "direct_answer",
                "confidence": 1.0,
                "reason": "空问题，使用默认回答",
                "suggested_tools": []
            }

        try:
            self.logger.debug(f"开始分析问题: {question[:50]}...")

            # 1. 基本特征分析
            features = self._extract_features(question)
            self.logger.debug(f"特征提取完成: {features}")

            # 2. 增强的关键词匹配
            keyword_scores = self._calculate_enhanced_keyword_scores(question)
            self.logger.debug(f"关键词评分: {keyword_scores}")

            # 3. 工具匹配分析（新增）
            tool_matches = self._match_tools(question)
            self.logger.debug(f"工具匹配: {tool_matches}")

            # 4. 上下文分析
            context_info = self._analyze_context(conversation_history)
            self.logger.debug(f"上下文分析: {context_info}")

            # 5. 综合决策（增强版：考虑LLM决策）
            decision = self._make_enhanced_decision(
                features,
                keyword_scores,
                tool_matches,
                context_info,
                llm_decision
            )

            self.logger.info(
                f"问题分析完成: action={decision['action']}, "
                f"confidence={decision['confidence']:.2f}, "
                f"suggested_tools={decision.get('suggested_tools', [])}"
            )

            return decision

        except Exception as e:
            self.logger.error(f"问题分析失败: {str(e)}", exc_info=True)
            return {
                "action": "direct_answer",
                "confidence": 0.5,
                "reason": f"分析失败，使用默认行动: {str(e)}",
                "suggested_tools": []
            }

    def _extract_features(self, question: str) -> Dict[str, Any]:
        features = {
            "original_question": question,
            "normalized_question": question.lower(),
            "length": len(question),
            "word_count": len(question.split()),
            "has_question_mark": "?" in question or "？" in question,
            "is_short": len(question) < self.short_question_length,
            "is_long": len(question) > self.long_question_length,
            "has_numbers": any(char.isdigit() for char in question),
            "has_english": any(char.isalpha() and ord(char) < 128 for char in question),
            "has_punctuation": any(char in "，。！？；：、" for char in question),
            "is_imperative": any(word in question for word in ["帮我", "请", "给我", "查询", "搜索"]),
            "is_interrogative": any(word in question for word in ["什么", "怎么", "为什么", "哪里", "谁", "如何"])
        }

        return features

    def _calculate_enhanced_keyword_scores(self, question: str) -> Dict[str, float]:
        scores = {
            "direct_answer": 0.0,
            "retrieval": 0.0,
            "tool_call": 0.0
        }

        question_lower = question.lower()

        for action, keyword_groups in self.action_keywords.items():
            total_weight = 0
            matched_weight = 0

            for group_name, keywords in keyword_groups.items():
                # 不同类型的关键词有不同的权重
                weight = self._get_keyword_group_weight(group_name)
                total_weight += weight

                # 检查是否匹配
                for keyword in keywords:
                    if keyword in question_lower:
                        matched_weight += weight
                        break  # 每组只计算一次

            # 归一化分数
            if total_weight > 0:
                scores[action] = matched_weight / total_weight

        return scores

    def _get_keyword_group_weight(self, group_name: str) -> float:
        weights = {
            # direct_answer相关
            "greetings": 1.0,
            "thanks": 1.0,
            "farewell": 1.0,
            "simple_questions": 0.5,
            "common_sense": 0.3,

            # retrieval相关
            "query_intent": 0.8,
            "document_related": 1.0,
            "detail_request": 0.6,
            "enterprise_info": 1.0,
            "history_request": 0.7,

            # tool_call相关
            "calculation": 1.0,
            "weather": 1.0,
            "time": 1.0,
            "translation": 1.0,
            "web_search": 0.9,
            "generation": 0.8,
            "conversion": 0.9
        }

        return weights.get(group_name, 0.5)

    def _match_tools(self, question: str) -> Dict[str, Any]:
        if not self.tool_registry:
            return {
                "matched_tools": [],
                "has_matches": False,
                "best_match": None
            }

        if self._has_explicit_retrieval_signal(question) and not self._has_explicit_external_tool_signal(question):
            self.logger.debug("检测到显式知识库检索信号，跳过工具匹配")
            return {
                "matched_tools": [],
                "has_matches": False,
                "best_match": None
            }

        matched_tools = []
        question_lower = question.lower()

        # 获取所有工具
        all_tools = self.tool_registry.get_all_tools()

        for tool_name, tool_instance in all_tools.items():
            definition = tool_instance.get_definition()

            # 简单的关键词匹配
            tool_keywords = self._get_tool_keywords(tool_name, definition)

            match_score = 0
            for keyword in tool_keywords:
                if keyword in question_lower:
                    match_score += 1

            if match_score > 0:
                matched_tools.append({
                    "name": tool_name,
                    "score": match_score,
                    "category": definition.category,
                    "description": definition.description
                })

        # 按匹配分数排序
        matched_tools.sort(key=lambda x: x["score"], reverse=True)

        return {
            "matched_tools": matched_tools,
            "has_matches": len(matched_tools) > 0,
            "best_match": matched_tools[0] if matched_tools else None
        }

    def _get_tool_keywords(self, tool_name: str, definition) -> List[str]:
        keywords = []

        # 从工具名称提取关键词
        if "calculator" in tool_name:
            keywords.extend(["计算", "算", "加", "减", "乘", "除"])
        elif "weather" in tool_name:
            keywords.extend(["天气", "气温", "温度"])
        elif "translation" in tool_name:
            keywords.extend(["翻译", "英文", "中文"])
        elif "datetime" in tool_name:
            keywords.extend(["时间", "日期", "今天", "明天"])
        elif "web_search" in tool_name:
            keywords.extend(["搜索", "联网", "互联网", "网页", "实时", "最新", "新闻"])
        elif "news" in tool_name:
            keywords.extend(["新闻", "资讯"])
        elif "wikipedia" in tool_name:
            keywords.extend(["百科", "维基"])
        elif "exchange_rate" in tool_name:
            keywords.extend(["汇率", "兑换", "货币"])
        elif "ip_lookup" in tool_name:
            keywords.extend(["ip", "地址", "位置"])
        elif "database" in tool_name:
            keywords.extend(["数据库", "数据表", "统计", "会话记录", "消息记录", "执行记录"])
        elif "novel" in tool_name:
            keywords.extend(["小说", "故事", "创作"])
        elif "script" in tool_name:
            keywords.extend(["脚本", "剧本"])
        elif "content_optimizer" in tool_name:
            keywords.extend(["优化", "改写", "润色"])

        return keywords

    def _has_explicit_retrieval_signal(self, question: str) -> bool:
        question_lower = question.lower()

        if any(keyword in question_lower for keyword in self.explicit_retrieval_keywords):
            return True

        return any(phrase in question_lower for phrase in self.explicit_retrieval_phrases)

    def _has_explicit_external_tool_signal(self, question: str) -> bool:
        question_lower = question.lower()
        return any(keyword in question_lower for keyword in self.explicit_external_tool_keywords)

    def _analyze_context(self, conversation_history: Optional[List]) -> Dict[str, Any]:
        if not conversation_history:
            return {
                "has_history": False,
                "history_length": 0,
                "last_action": None,
                "recent_actions": [],
                "is_follow_up": False
            }

        # 提取最近的行动类型
        recent_actions = []
        for msg in reversed(conversation_history[-5:]):  # 最近5条
            if isinstance(msg, dict) and "action" in msg:
                recent_actions.append(msg["action"])

        last_action = recent_actions[0] if recent_actions else None
        is_follow_up = len(conversation_history) > 0

        return {
            "has_history": True,
            "history_length": len(conversation_history),
            "last_action": last_action,
            "recent_actions": recent_actions,
            "is_follow_up": is_follow_up
        }

    def _make_enhanced_decision(
        self,
        features: Dict[str, Any],
        keyword_scores: Dict[str, float],
        tool_matches: Dict[str, Any],
        context_info: Dict[str, Any],
        llm_decision: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        # 初始化各行动的得分
        action_scores = {
            "direct_answer": 0.0,
            "retrieval": 0.0,
            "tool_call": 0.0
        }

        # 1. 优先处理简单问题（问候、感谢等）- 强制判断
        if keyword_scores.get("direct_answer", 0) > 0.5:
            # 检查是否是明确的简单问题
            simple_keywords = ["你好", "您好", "hi", "hello", "谢谢", "感谢", "再见", "拜拜"]
            question_lower = features.get("original_question", "").lower()
            if any(kw in question_lower for kw in simple_keywords):
                self.logger.debug("检测到简单问候/感谢，强制使用direct_answer")
                return {
                    "action": "direct_answer",
                    "confidence": 0.95,
                    "reason": "简单问候或感谢，直接回答",
                    "suggested_tools": [],
                    "action_scores": {"direct_answer": 0.95, "retrieval": 0.0, "tool_call": 0.0},
                    "features": features,
                    "tool_matches": tool_matches
                }

        # 1.5 优先处理显式知识库/文档检索问题
        if self._has_explicit_retrieval_signal(features.get("original_question", "")) and not self._has_explicit_external_tool_signal(features.get("original_question", "")):
            self.logger.debug("检测到显式知识库检索意图，强制使用retrieval")
            return {
                "action": "retrieval",
                "confidence": 0.92,
                "reason": "问题明确限定在知识库/文档范围内，优先执行知识检索",
                "suggested_tools": [],
                "action_scores": {"direct_answer": 0.0, "retrieval": 0.92, "tool_call": 0.0},
                "features": features,
                "tool_matches": {"matched_tools": [], "has_matches": False, "best_match": None}
            }

        # 2. 基于关键词匹配的分数（提高权重到50%）
        for action, score in keyword_scores.items():
            if action in action_scores:
                action_scores[action] += score * 0.5
                self.logger.debug(f"关键词匹配 {action}: {score * 0.5:.2f}")

        # 3. 基于工具匹配的分数（降低权重到30%）
        if tool_matches["has_matches"]:
            action_scores["tool_call"] += 0.3
            self.logger.debug(f"工具匹配成功: {tool_matches['best_match']['name']}, 加分0.3")

        # 4. 如果有LLM决策，作为参考（降低权重到20%）
        if llm_decision and "action" in llm_decision:
            llm_action = llm_decision["action"]
            llm_confidence = llm_decision.get("confidence", 0.5)

            if llm_action in action_scores:
                action_scores[llm_action] += llm_confidence * 0.2
                self.logger.debug(f"LLM决策参考: {llm_action}, 加分: {llm_confidence * 0.2:.2f}")

        # 5. 基于问题长度的分数
        if features["is_short"]:
            action_scores["direct_answer"] += 0.15
            self.logger.debug("短问题，direct_answer加分0.15")
        elif features["is_long"]:
            action_scores["retrieval"] += 0.1
            self.logger.debug("长问题，retrieval加分0.1")

        # 6. 基于问题特征的调整
        if features["has_question_mark"]:
            if features["is_interrogative"]:
                # 疑问词开头的问题，可能需要检索
                action_scores["retrieval"] += 0.05
                self.logger.debug("疑问词问题，retrieval加分0.05")
            else:
                action_scores["tool_call"] += 0.03
                self.logger.debug("问号但非疑问词，tool_call加分0.03")

        if features["is_imperative"]:
            action_scores["tool_call"] += 0.08
            self.logger.debug("祈使句，tool_call加分0.08")

        # 7. 基于上下文的调整（降低权重）
        if context_info["is_follow_up"]:
            last_action = context_info["last_action"]
            if last_action == "retrieval":
                action_scores["retrieval"] += 0.05
                self.logger.debug("上次是retrieval，加分0.05")
            elif last_action == "tool_call":
                action_scores["tool_call"] += 0.03
                self.logger.debug("上次是tool_call，加分0.03")

        # 8. 选择得分最高的行动
        best_action = max(action_scores, key=action_scores.get)
        confidence = action_scores[best_action]

        self.logger.debug(f"最终得分: {action_scores}")

        # 9. 归一化置信度
        max_possible_score = 1.2
        confidence = min(confidence / max_possible_score, 1.0)

        # 10. 推荐工具（如果是tool_call）
        suggested_tools = []
        if best_action == "tool_call" and tool_matches["has_matches"]:
            # 推荐前3个匹配的工具
            suggested_tools = [
                tool["name"] for tool in tool_matches["matched_tools"][:3]
            ]

        # 11. low confidence fallback handling
        if confidence < 0.35:
            llm_action = llm_decision.get("action") if llm_decision else None
            llm_confidence = llm_decision.get("confidence", 0.0) if llm_decision else 0.0
            retrieval_signal = (
                best_action == "retrieval"
                and (
                    keyword_scores.get("retrieval", 0.0) >= 0.2
                    or features.get("is_interrogative", False)
                    or "知识库" in features.get("original_question", "")
                )
            )

            if llm_action in {"retrieval", "tool_call"} and llm_confidence >= 0.75:
                self.logger.debug(
                    f"置信度偏低但LLM强烈建议{llm_action}({llm_confidence:.2f})，保留该动作"
                )
                best_action = llm_action
                confidence = max(confidence, min(llm_confidence, 0.85))
                reason = f"LLM对{llm_action}决策置信度较高，优先采用该动作"
            elif retrieval_signal:
                self.logger.debug("置信度偏低但检测到明显检索意图，保留retrieval")
                best_action = "retrieval"
                confidence = max(confidence, 0.45)
                reason = "检测到明确检索意图，优先执行知识检索"
            else:
                self.logger.debug(f"置信度过低({confidence:.2f})，使用默认direct_answer")
                best_action = "direct_answer"
                confidence = 0.5
                reason = "置信度较低，使用默认直接回答"
        else:
            reason = self._generate_enhanced_reason(
                best_action, features, keyword_scores, tool_matches
            )

        return {
            "action": best_action,
            "confidence": confidence,
            "reason": reason,
            "suggested_tools": suggested_tools,
            "action_scores": action_scores,
            "features": features,
            "tool_matches": tool_matches
        }

    def _make_decision(
        self,
        features: Dict[str, Any],
        keyword_scores: Dict[str, float],
        context_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        # 调用增强版决策方法
        return self._make_enhanced_decision(
            features,
            keyword_scores,
            {"matched_tools": [], "has_matches": False, "best_match": None},
            context_info,
            None
        )

    def _generate_enhanced_reason(
        self,
        action: str,
        features: Dict[str, Any],
        keyword_scores: Dict[str, float],
        tool_matches: Dict[str, Any]
    ) -> str:
        reasons = []

        if action == "direct_answer":
            if features["is_short"]:
                reasons.append("问题较短，可能是简单问候或常识问题")
            if keyword_scores.get("direct_answer", 0) > 0.3:
                reasons.append("包含直接回答的关键词")

        elif action == "retrieval":
            if features["is_long"]:
                reasons.append("问题较长，可能需要详细信息")
            if keyword_scores.get("retrieval", 0) > 0.3:
                reasons.append("包含检索相关的关键词")
            if features["is_interrogative"]:
                reasons.append("包含疑问词，可能需要查询知识库")

        elif action == "tool_call":
            if tool_matches["has_matches"]:
                best_tool = tool_matches["best_match"]["name"]
                reasons.append(f"匹配到工具: {best_tool}")
            if keyword_scores.get("tool_call", 0) > 0.3:
                reasons.append("包含工具调用相关的关键词")
            if features["has_numbers"]:
                reasons.append("包含数字，可能需要计算")
            if features["is_imperative"]:
                reasons.append("包含祈使语气，可能需要执行操作")

        if not reasons:
            reasons.append("基于综合分析的决策")

        return "；".join(reasons)

    def _generate_reason(
        self,
        action: str,
        features: Dict[str, Any],
        keyword_scores: Dict[str, float]
    ) -> str:
        return self._generate_enhanced_reason(
            action,
            features,
            keyword_scores,
            {"matched_tools": [], "has_matches": False, "best_match": None}
        )

    def validate_decision(self, decision: Dict[str, Any]) -> bool:
        required_fields = ["action", "confidence", "reason"]
        if not all(field in decision for field in required_fields):
            self.logger.warning(f"决策缺少必需字段: {required_fields}")
            return False

        valid_actions = ["direct_answer", "retrieval", "tool_call", "multi_agent"]
        if decision["action"] not in valid_actions:
            self.logger.warning(f"无效的行动类型: {decision['action']}")
            return False

        if not (0.0 <= decision["confidence"] <= 1.0):
            self.logger.warning(f"无效的置信度: {decision['confidence']}")
            return False

        return True

    def adjust_decision_by_feedback(
        self,
        decision: Dict[str, Any],
        feedback: Dict[str, Any]
    ) -> Dict[str, Any]:
        # TODO: 实现基于反馈的决策调整
        # 这可以用于未来的强化学习或在线学习
        self.logger.info("基于反馈的决策调整功能尚未实现")
        return decision

    def get_available_tools_summary(self) -> Dict[str, Any]:
        if not self.tool_registry:
            return {
                "total_count": 0,
                "categories": {},
                "tools": []
            }

        all_tools = self.tool_registry.get_all_tools()

        summary = {
            "total_count": len(all_tools),
            "categories": {},
            "tools": []
        }

        for tool_name, tool_instance in all_tools.items():
            definition = tool_instance.get_definition()
            category = definition.category

            if category not in summary["categories"]:
                summary["categories"][category] = 0
            summary["categories"][category] += 1

            summary["tools"].append({
                "name": tool_name,
                "category": category,
                "description": definition.description[:50] + "..."
            })

        return summary

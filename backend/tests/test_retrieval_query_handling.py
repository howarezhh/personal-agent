import logging
from types import SimpleNamespace

import pytest

from backend.agents.retrieval.keyword_retriever import KeywordRetriever
from backend.agents.retrieval.query_rewriter import QueryRewriter
from backend.agents.retrieval.reranker import Reranker
from backend.agents.retrieval.retrieval_agent import RetrievalAgent


def _build_test_agent(vector_store) -> RetrievalAgent:
    agent = RetrievalAgent.__new__(RetrievalAgent)
    agent.logger = logging.getLogger("test_retrieval_agent")
    agent.vector_store = vector_store
    agent.vector_enabled = True
    agent.top_k = 2
    agent.similarity_threshold = 0.0
    agent.distance_metric = "l2"
    agent.enable_hybrid_retrieval = True
    agent.keyword_top_k = 4
    agent.keyword_min_score = 0.0
    agent.vector_weight = 0.65
    agent.keyword_weight = 0.35
    agent.keyword_retriever = KeywordRetriever()
    return agent


def test_query_rewriter_filters_placeholder_queries():
    rewriter = QueryRewriter.__new__(QueryRewriter)
    rewriter.logger = logging.getLogger("test_query_rewriter")

    queries = rewriter._sanitize_rewritten_queries(
        original_query='知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的',
        rewritten_queries=[
            '优化查询1：基于核心意图和扩展术语',
            '重写查询2：结合同义和相关概念',
            'SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究 作者',
        ],
    )

    assert queries[0] == '知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的'
    assert 'SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究 作者' in queries
    assert all('优化查询' not in query for query in queries)
    assert all('重写查询' not in query for query in queries)


def test_retrieval_agent_extracts_exact_phrase_from_quotes():
    agent = RetrievalAgent.__new__(RetrievalAgent)

    phrases = agent._extract_exact_phrases(
        '知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的'
    )

    assert phrases == ['SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究']


def test_retrieval_agent_builds_queries_with_original_and_exact_phrase():
    agent = RetrievalAgent.__new__(RetrievalAgent)

    queries = agent._build_search_queries(
        '知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的',
        {
            'rewritten_queries': [
                '知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的',
                'SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究 作者',
            ]
        },
    )

    assert queries[0] == '知识库里面“SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究”是谁写的'
    assert 'SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究' in queries
    assert 'SURF 算法与感知哈希算法结合的相似图像和视频检索方法研究 作者' in queries



@pytest.mark.asyncio
async def test_retrieval_agent_merges_duplicate_hits_and_keeps_best_score():
    agent = RetrievalAgent.__new__(RetrievalAgent)
    agent.logger = logging.getLogger("test_retrieval_agent")
    agent.vector_enabled = True
    agent.top_k = 2
    agent.similarity_threshold = 0.0
    agent.distance_metric = "l2"

    class FakeVectorStore:
        collection = None

        @staticmethod
        def normalize_where_filter(where):
            return where

        def search(self, query, n_results, where):
            assert where == {"user_id": "user-1"}
            assert n_results >= 2
            if query == "q1":
                return {
                    "ids": [["doc-1"]],
                    "documents": [["alpha content"]],
                    "distances": [[0.7]],
                    "metadatas": [[{"source": "alpha.txt"}]],
                }
            return {
                "ids": [["doc-1", "doc-2"]],
                "documents": [["alpha content", "beta content"]],
                "distances": [[0.1, 0.3]],
                "metadatas": [[{"source": "alpha.txt"}, {"source": "beta.txt"}]],
            }

    agent.vector_store = FakeVectorStore()
    agent_input = SimpleNamespace(user_id="user-1", metadata={}, content="question")
    agent._extract_exact_phrases = lambda query: []

    results = await agent._retrieve_documents(["q1", "q2"], agent_input)

    assert results[0]["id"] == "doc-1"
    assert results[0]["score"] > results[1]["score"]
    assert results[0]["metadata"]["query_hit_count"] == 2


def test_reranker_promotes_query_relevant_result():
    reranker = Reranker()
    results = [
        {
            "id": "doc-1",
            "content": "This is a general overview document.",
            "score": 0.82,
            "metadata": {"source": "overview.txt", "source_type": "article"},
        },
        {
            "id": "doc-2",
            "content": "The knowledge graph construction method organizes entities, relations, and retrieval structure.",
            "score": 0.78,
            "metadata": {
                "source": "knowledge_graph_construction_method.pdf",
                "source_type": "article",
                "query_hit_count": 2,
            },
        },
    ]

    reranked = reranker.rerank(results, 'Explain "knowledge graph construction method"', top_k=2)

    assert reranked[0]["id"] == "doc-2"
    assert reranked[0]["score_breakdown"]["query_relevance"] > reranked[1]["score_breakdown"]["query_relevance"]

def test_keyword_retriever_prefers_exact_phrase_document():
    retriever = KeywordRetriever()
    index = retriever.build_index(
        ids=["doc-1", "doc-2"],
        documents=[
            "High quality development is the primary task of modernization.",
            "Modernization requires steady improvement in governance.",
        ],
        metadatas=[
            {"source": "policy.pdf"},
            {"source": "overview.txt"},
        ],
    )

    results = retriever.search(index, "high quality development", top_k=2)

    assert len(results) == 1
    assert results[0]["id"] == "doc-1"
    assert results[0]["metadata"]["keyword_score"] > 0


@pytest.mark.asyncio
async def test_retrieval_agent_returns_keyword_results_when_vector_search_empty():
    class FakeCollection:
        @staticmethod
        def get(where, include):
            assert where == {"user_id": "user-1"}
            assert include == ["documents", "metadatas"]
            return {
                "ids": ["doc-1", "doc-2"],
                "documents": [
                    "High quality development is the primary task of modernization.",
                    "Modernization requires better governance.",
                ],
                "metadatas": [
                    {"source": "policy.pdf"},
                    {"source": "overview.txt"},
                ],
            }

    class FakeVectorStore:
        collection = FakeCollection()

        @staticmethod
        def normalize_where_filter(where):
            return where

        def search(self, query, n_results, where):
            assert where == {"user_id": "user-1"}
            return {
                "ids": [[]],
                "documents": [[]],
                "distances": [[]],
                "metadatas": [[]],
            }

    agent = _build_test_agent(FakeVectorStore())
    agent_input = SimpleNamespace(user_id="user-1", metadata={}, content="high quality development")

    results = await agent._retrieve_documents(["high quality development"], agent_input)

    assert results
    assert results[0]["id"] == "doc-1"
    assert "keyword" in results[0]["metadata"]["match_sources"]
    assert results[0]["metadata"]["score_components"]["keyword_score"] > 0


@pytest.mark.asyncio
async def test_retrieval_agent_hybrid_prefers_multi_signal_result():
    class FakeCollection:
        @staticmethod
        def get(where, include):
            assert where == {"user_id": "user-1"}
            assert include == ["documents", "metadatas"]
            return {
                "ids": ["doc-1", "doc-2"],
                "documents": [
                    "knowledge graph construction method includes entity extraction and relation extraction.",
                    "graph system overview and application scenarios.",
                ],
                "metadatas": [
                    {"source": "kg_method.pdf"},
                    {"source": "overview.txt"},
                ],
            }

    class FakeVectorStore:
        collection = FakeCollection()

        @staticmethod
        def normalize_where_filter(where):
            return where

        def search(self, query, n_results, where):
            assert where == {"user_id": "user-1"}
            return {
                "ids": [["doc-2", "doc-1"]],
                "documents": [[
                    "graph system overview and application scenarios.",
                    "knowledge graph construction method includes entity extraction and relation extraction.",
                ]],
                "distances": [[0.22, 0.35]],
                "metadatas": [[
                    {"source": "overview.txt"},
                    {"source": "kg_method.pdf"},
                ]],
            }

    agent = _build_test_agent(FakeVectorStore())
    agent_input = SimpleNamespace(user_id="user-1", metadata={}, content="knowledge graph construction method")

    results = await agent._retrieve_documents(["knowledge graph construction method"], agent_input)

    assert results[0]["id"] == "doc-1"
    assert set(results[0]["metadata"]["match_sources"]) >= {"keyword", "vector"}
    assert results[0]["score"] > results[1]["score"]


def test_vector_search_filter_preserves_user_isolation_and_ignores_none_values():
    agent = RetrievalAgent.__new__(RetrievalAgent)

    search_filter = agent._build_vector_search_filter(
        SimpleNamespace(
            user_id="user-1",
            metadata={
                "vector_search_filter": {
                    "user_id": "user-2",
                    "knowledge_base_id": "kb-1",
                    "conversation_id": None,
                }
            },
        )
    )

    assert search_filter == {"user_id": "user-1", "knowledge_base_id": "kb-1"}


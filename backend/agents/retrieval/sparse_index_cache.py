# -*- coding: utf-8 -*-

from __future__ import annotations

"""
稀疏索引缓存模块。

该模块负责缓存指定检索作用域下的：
- 过滤后的语料副本；
- 基于语料构建的 BM25 风格索引；
- 索引构建来源与时间戳。

这样可以把“每次查询都临时构建关键词索引”的成本，收敛为：
- 首次查询构建一次；
- 文档入库/更新/删除时按作用域主动刷新或失效。
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Optional

from cachetools import TTLCache

from backend.utils.logger import get_logger


@dataclass
class SparseIndexBundle:
    """单个检索作用域下缓存的语料与关键词索引。"""

    scope_key: str
    search_filter: Dict[str, Any]
    corpus: Dict[str, Any]
    keyword_index: Dict[str, Any]
    built_at: float
    source: str


class SparseIndexCache:
    """按检索作用域缓存稀疏索引。"""

    def __init__(self, *, enabled: bool = True, ttl_seconds: int = 1800, max_entries: int = 64):
        # `self.logger`：输出缓存命中、构建、刷新、失效等关键日志。
        self.logger = get_logger("sparse_index_cache")
        # `self.enabled`：统一控制缓存启停，便于配置回退。
        self.enabled = bool(enabled)
        # `self._cache`：TTL 缓存，自动淘汰过期作用域。
        self._cache: TTLCache[str, SparseIndexBundle] = TTLCache(
            maxsize=max(1, int(max_entries)),
            ttl=max(1, int(ttl_seconds)),
        )
        # `self._lock`：保护并发访问与刷新，避免重复构建同一作用域索引。
        self._lock = threading.RLock()

    @staticmethod
    def build_scope_key(search_filter: Optional[Dict[str, Any]], *, collection_name: str = "knowledge_base") -> str:
        """根据过滤条件构建稳定缓存键。"""
        normalized_filter = search_filter or {}
        normalized_json = json.dumps(normalized_filter, ensure_ascii=False, sort_keys=True, default=str)
        return f"{collection_name}:{normalized_json}"

    def get(self, *, search_filter: Optional[Dict[str, Any]], collection_name: str) -> Optional[SparseIndexBundle]:
        """读取缓存中的索引 bundle。"""
        if not self.enabled:
            return None
        scope_key = self.build_scope_key(search_filter, collection_name=collection_name)
        with self._lock:
            bundle = self._cache.get(scope_key)
        if bundle is not None:
            self.logger.info("稀疏索引缓存命中: scope_key=%s", scope_key)
        return bundle

    def set(self, bundle: SparseIndexBundle) -> SparseIndexBundle:
        """写入新的索引 bundle。"""
        if not self.enabled:
            return bundle
        with self._lock:
            self._cache[bundle.scope_key] = bundle
        self.logger.info("稀疏索引缓存已写入: scope_key=%s, source=%s", bundle.scope_key, bundle.source)
        return bundle

    def get_or_build(
        self,
        *,
        search_filter: Optional[Dict[str, Any]],
        collection_name: str,
        builder: Callable[[], SparseIndexBundle],
    ) -> SparseIndexBundle:
        """优先命中缓存，否则构建并写入。"""
        scope_key = self.build_scope_key(search_filter, collection_name=collection_name)
        if not self.enabled:
            return builder()
        with self._lock:
            bundle = self._cache.get(scope_key)
            if bundle is not None:
                self.logger.info("稀疏索引缓存命中: scope_key=%s", scope_key)
                return bundle
        bundle = builder()
        return self.set(bundle)

    def invalidate(self, *, search_filter: Optional[Dict[str, Any]], collection_name: str) -> None:
        """按作用域失效缓存。"""
        if not self.enabled:
            return
        scope_key = self.build_scope_key(search_filter, collection_name=collection_name)
        with self._lock:
            self._cache.pop(scope_key, None)
        self.logger.info("稀疏索引缓存已失效: scope_key=%s", scope_key)

    def clear(self) -> None:
        """清空全部缓存，主要用于集合重置或测试场景。"""
        with self._lock:
            self._cache.clear()
        self.logger.info("稀疏索引缓存已全部清空")

    def invalidate_from_metadatas(self, *, metadatas: Iterable[Dict[str, Any]] | None, collection_name: str) -> None:
        """根据文档元数据批量失效相关作用域缓存。"""
        if not self.enabled or not metadatas:
            return
        seen_scope_keys: set[str] = set()
        for metadata in metadatas:
            if not isinstance(metadata, dict):
                continue
            for scope_filter in self._candidate_scope_filters(metadata):
                scope_key = self.build_scope_key(scope_filter, collection_name=collection_name)
                if scope_key in seen_scope_keys:
                    continue
                seen_scope_keys.add(scope_key)
                with self._lock:
                    self._cache.pop(scope_key, None)
                self.logger.info("稀疏索引缓存已按元数据失效: scope_key=%s", scope_key)

    def warm_scope(
        self,
        *,
        search_filter: Optional[Dict[str, Any]],
        collection_name: str,
        corpus_loader: Callable[[Dict[str, Any]], tuple[Dict[str, Any], str]],
        keyword_index_builder: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> SparseIndexBundle:
        """主动刷新指定作用域缓存，供入库后预热使用。"""
        normalized_filter = dict(search_filter or {})
        corpus, source = corpus_loader(normalized_filter)
        bundle = SparseIndexBundle(
            scope_key=self.build_scope_key(normalized_filter, collection_name=collection_name),
            search_filter=normalized_filter,
            corpus=corpus,
            keyword_index=keyword_index_builder(corpus),
            built_at=time.time(),
            source=source,
        )
        return self.set(bundle)

    @staticmethod
    def _candidate_scope_filters(metadata: Dict[str, Any]) -> list[Dict[str, Any]]:
        """从文档元数据提取可能的缓存作用域。

        说明：
        - 优先按 `user_id + knowledge_base_id`；
        - 若没有知识库，则退化为 `user_id`；
        - 若只有知识库，也保留单独作用域，兼容后台批量重建任务。
        """
        user_id = metadata.get("user_id")
        knowledge_base_id = metadata.get("knowledge_base_id")
        scope_filters: list[Dict[str, Any]] = []
        if user_id and knowledge_base_id:
            scope_filters.append({"user_id": user_id, "knowledge_base_id": knowledge_base_id})
        if user_id:
            scope_filters.append({"user_id": user_id})
        if knowledge_base_id:
            scope_filters.append({"knowledge_base_id": knowledge_base_id})
        if not scope_filters:
            scope_filters.append({})
        return scope_filters


_SPARSE_INDEX_CACHE: Optional[SparseIndexCache] = None


def get_sparse_index_cache(*, enabled: bool = True, ttl_seconds: int = 1800, max_entries: int = 64) -> SparseIndexCache:
    """返回进程级共享的稀疏索引缓存实例。"""
    global _SPARSE_INDEX_CACHE
    if _SPARSE_INDEX_CACHE is None:
        _SPARSE_INDEX_CACHE = SparseIndexCache(
            enabled=enabled,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
        )
        return _SPARSE_INDEX_CACHE

    _SPARSE_INDEX_CACHE.enabled = bool(enabled)
    return _SPARSE_INDEX_CACHE


__all__ = ["SparseIndexBundle", "SparseIndexCache", "get_sparse_index_cache"]

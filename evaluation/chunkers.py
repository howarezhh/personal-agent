from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol

from backend.file_processors.chunker import DocumentChunker


@dataclass(frozen=True)
class ExperimentChunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_index: int
    metadata: Dict[str, Any]


class Chunker(Protocol):
    name: str
    chunk_size: int
    chunk_overlap: int

    def split(self, text: str, *, document_id: str, metadata: Dict[str, Any] | None = None) -> List[ExperimentChunk]: ...


class FixedWindowChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap must not be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.name = f"fixed_{chunk_size}_{chunk_overlap}"

    def split(self, text: str, *, document_id: str, metadata: Dict[str, Any] | None = None) -> List[ExperimentChunk]:
        base_metadata = dict(metadata or {})
        chunks: List[ExperimentChunk] = []
        start = 0
        chunk_index = 0

        while start < len(text):
            end = min(len(text), start + self.chunk_size)
            content = text[start:end].strip()
            if content:
                chunk_metadata = {
                    **base_metadata,
                    "chunk_index": chunk_index,
                    "chunking_strategy": self.name,
                    "start_char": start,
                    "end_char": end,
                }
                chunks.append(
                    ExperimentChunk(
                        chunk_id=f"{self.name}::{document_id}::{chunk_index}",
                        document_id=document_id,
                        text=content,
                        chunk_index=chunk_index,
                        metadata=chunk_metadata,
                    )
                )
                chunk_index += 1

            if end >= len(text):
                break
            start = max(start + 1, end - self.chunk_overlap)

        return chunks


class ParagraphChunker:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.name = f"paragraph_{chunk_size}_{chunk_overlap}"
        self._chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split(self, text: str, *, document_id: str, metadata: Dict[str, Any] | None = None) -> List[ExperimentChunk]:
        base_metadata = dict(metadata or {})
        chunks: List[ExperimentChunk] = []

        for text_chunk in self._chunker.chunk_text(text, base_metadata):
            # ?????DocumentChunker ???? FileChunk??????? chunk_index?
            # ????????????????? index ???
            chunk_index = int(text_chunk.chunk_index)
            chunk_metadata = {
                **dict(text_chunk.metadata or {}),
                "chunking_strategy": self.name,
            }
            chunks.append(
                ExperimentChunk(
                    chunk_id=f"{self.name}::{document_id}::{chunk_index}",
                    document_id=document_id,
                    text=text_chunk.content,
                    chunk_index=chunk_index,
                    metadata=chunk_metadata,
                )
            )

        return chunks


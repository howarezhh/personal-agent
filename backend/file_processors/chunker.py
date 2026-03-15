
from typing import List, Dict, Any
from dataclasses import dataclass
import logging


@dataclass
class TextChunk:
    content: str
    index: int
    metadata: Dict[str, Any]

    @property
    def page_number(self) -> int | None:
        if not self.metadata:
            return None
        return self.metadata.get("page_number")

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "index": self.index,
            "metadata": self.metadata
        }


class DocumentChunker:
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        separator: str = "\n\n"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separator = separator
        self.logger = logging.getLogger(self.__class__.__name__)

    def chunk_text(
        self,
        text: str,
        metadata: Dict[str, Any] = None
    ) -> List[TextChunk]:
        if not text:
            return []

        if metadata is None:
            metadata = {}

        chunks = []

        # 首先按分隔符分割
        sections = text.split(self.separator)

        current_chunk = ""
        chunk_index = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # 如果当前section加上current_chunk超过chunk_size
            if len(current_chunk) + len(section) + len(self.separator) > self.chunk_size:
                # 保存当前chunk
                if current_chunk:
                    chunks.append(TextChunk(
                        content=current_chunk.strip(),
                        index=chunk_index,
                        metadata={**metadata, "chunk_index": chunk_index}
                    ))
                    chunk_index += 1

                # 如果section本身就很长，需要进一步分割
                if len(section) > self.chunk_size:
                    sub_chunks = self._split_long_text(section, chunk_index, metadata)
                    chunks.extend(sub_chunks)
                    chunk_index += len(sub_chunks)
                    current_chunk = ""
                else:
                    # 使用overlap：从上一个已保存的chunk获取重叠部分
                    if chunks and self.chunk_overlap > 0:
                        last_chunk_content = chunks[-1].content
                        overlap_text = last_chunk_content[-self.chunk_overlap:]
                        current_chunk = overlap_text + self.separator + section
                    else:
                        current_chunk = section
            else:
                # 添加到当前chunk
                if current_chunk:
                    current_chunk += self.separator + section
                else:
                    current_chunk = section

        # 保存最后一个chunk
        if current_chunk:
            chunks.append(TextChunk(
                content=current_chunk.strip(),
                index=chunk_index,
                metadata={**metadata, "chunk_index": chunk_index}
            ))

        self.logger.info(f"Split text into {len(chunks)} chunks")
        return chunks

    def _split_long_text(
        self,
        text: str,
        start_index: int,
        metadata: Dict[str, Any]
    ) -> List[TextChunk]:
        chunks = []
        start = 0
        chunk_index = start_index

        while start < len(text):
            end = start + self.chunk_size
            actual_end = end  # 记录实际的结束位置

            # 尝试在合适的位置断开（句号、换行等）
            if end < len(text):
                # 向后查找合适的断点
                for breakpoint in ['. ', '。', '\n', ' ']:
                    pos = text.rfind(breakpoint, start, end)
                    if pos != -1:
                        actual_end = pos + len(breakpoint)
                        break

            chunk_text = text[start:actual_end].strip()
            if chunk_text:
                chunks.append(TextChunk(
                    content=chunk_text,
                    index=chunk_index,
                    metadata={**metadata, "chunk_index": chunk_index}
                ))
                chunk_index += 1

            # 移动到下一个位置（考虑overlap）
            # 使用actual_end而不是end，确保overlap计算正确
            if self.chunk_overlap > 0 and actual_end < len(text):
                start = max(start + 1, actual_end - self.chunk_overlap)
            else:
                start = actual_end

        return chunks

    def chunk_with_pages(
        self,
        pages: List[Dict[str, Any]],
        base_metadata: Dict[str, Any] = None
    ) -> List[TextChunk]:
        if base_metadata is None:
            base_metadata = {}

        all_chunks = []

        for page in pages:
            page_number = page.get("page_number", 0)
            page_text = page.get("text", "")

            if not page_text:
                continue

            # 为每页添加页码元数据
            page_metadata = {
                **base_metadata,
                "page_number": page_number
            }

            # 分割页面文本
            page_chunks = self.chunk_text(page_text, page_metadata)
            all_chunks.extend(page_chunks)

        # 重新编号
        for i, chunk in enumerate(all_chunks):
            chunk.index = i
            chunk.metadata["chunk_index"] = i

        return all_chunks

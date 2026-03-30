from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, Sequence


DEFAULT_TEXT_ENCODINGS: tuple[str, ...] = (
    "utf-8",
    "utf-8-sig",
    "gb18030",
    "gbk",
    "gb2312",
    "big5",
    "latin-1",
)

_HTML_CHARSET_RE = re.compile(rb"<meta[^>]+charset=[\"']?\s*([A-Za-z0-9_.-]+)", re.IGNORECASE)
_HTML_CONTENT_TYPE_RE = re.compile(
    rb"<meta[^>]+content=[\"'][^\"']*charset=([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)


def _deduplicate_preserve_order(items: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for item in items:
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        results.append(value)
    return results


def _decode_with_charset_normalizer(raw_bytes: bytes) -> tuple[str, str] | None:
    try:
        from charset_normalizer import from_bytes
    except Exception:
        return None

    try:
        best_match = from_bytes(raw_bytes).best()
    except Exception:
        return None

    if best_match is None:
        return None

    text = str(best_match)
    if not text:
        return None
    return text, str(best_match.encoding or "charset-normalizer")


def _decode_bytes(raw_bytes: bytes, encodings: Sequence[str]) -> tuple[str, str]:
    normalized_encodings = _deduplicate_preserve_order(encodings)
    loss_tolerant_encodings = {"latin-1"}

    for encoding in normalized_encodings:
        if encoding in loss_tolerant_encodings:
            continue
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    detected = _decode_with_charset_normalizer(raw_bytes)
    if detected is not None:
        return detected

    for encoding in normalized_encodings:
        if encoding not in loss_tolerant_encodings:
            continue
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode("utf-8", errors="replace"), "utf-8-replace"


def detect_html_declared_encoding(raw_bytes: bytes) -> str | None:
    sample = raw_bytes[:4096]
    for pattern in (_HTML_CHARSET_RE, _HTML_CONTENT_TYPE_RE):
        match = pattern.search(sample)
        if match:
            return match.group(1).decode("ascii", errors="ignore").strip() or None
    return None


def read_text_file_with_fallback(
    path: str | Path,
    *,
    primary_encoding: str | None = None,
    fallback_encodings: Sequence[str] | None = None,
) -> tuple[str, str]:
    raw_bytes = Path(path).read_bytes()
    candidate_encodings = [primary_encoding, *(fallback_encodings or DEFAULT_TEXT_ENCODINGS)]
    return _decode_bytes(raw_bytes, candidate_encodings)


def read_html_text_with_fallback(path: str | Path) -> tuple[str, str]:
    raw_bytes = Path(path).read_bytes()
    declared_encoding = detect_html_declared_encoding(raw_bytes)
    candidate_encodings = [
        declared_encoding,
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
        "big5",
        "latin-1",
    ]
    return _decode_bytes(raw_bytes, candidate_encodings)

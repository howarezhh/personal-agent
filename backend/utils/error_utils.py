from __future__ import annotations

import re
from typing import Any, Dict, Optional

from backend.contracts.errors import ErrorCode


_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\b\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+"),
)


def sanitize_error_message(error: Any, fallback: str = "execution failed") -> str:
    text = str(error or "").strip()
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text or fallback


def build_error_metadata(
    *,
    error_code: str = ErrorCode.SYSTEM_INTERNAL_ERROR.value,
    error_type: str = "execution_error",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    merged_metadata = dict(metadata or {})
    merged_metadata.setdefault("error_code", error_code)
    merged_metadata.setdefault("error_type", error_type)
    return merged_metadata

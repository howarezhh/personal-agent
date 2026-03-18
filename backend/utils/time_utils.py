from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a UTC timestamp while preserving the project's naive-UTC storage semantics."""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_now_iso_z(*, timespec: str = "seconds") -> str:
    return datetime.now(UTC).isoformat(timespec=timespec).replace("+00:00", "Z")

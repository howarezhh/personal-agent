"""Fail when checked-in OpenAPI schema drifts from runtime schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app


def main() -> int:
    target = PROJECT_ROOT / "docs/api/openapi.json"
    if not target.exists():
        print("docs/api/openapi.json is missing")
        return 1

    expected = json.loads(target.read_text(encoding="utf-8"))
    actual = app.openapi()

    if expected != actual:
        print("OpenAPI drift detected. Run: python scripts/contracts/export_openapi.py")
        return 1

    print("OpenAPI schema is in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

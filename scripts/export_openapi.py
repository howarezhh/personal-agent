"""Export OpenAPI schema from the FastAPI app."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app


def main() -> None:
    output_path = Path("docs/api/openapi.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI exported to {output_path}")


if __name__ == "__main__":
    main()

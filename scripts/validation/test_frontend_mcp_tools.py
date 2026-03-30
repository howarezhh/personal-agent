from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from httpx import ASGITransport, AsyncClient

from backend.api.dependencies import get_current_user
from backend.main import app, runtime_service
from backend.models.user import User


PAYLOADS: dict[str, dict[str, Any]] = {
    "exchange_rate_mcp": {"from_currency": "USD", "to_currency": "CNY", "amount": 10},
    "ip_lookup_mcp": {"language": "en"},
    "news_mcp": {"category": "technology", "country": "us", "page_size": 3},
    "weather_mcp": {"city": "Shanghai", "forecast_days": 1},
    "wikipedia_mcp": {"query": "OpenAI", "language": "en", "limit": 2},
}


async def main() -> None:
    fake_user = User(
        user_id="frontend-mcp-test",
        username="frontend-mcp-test",
        email="frontend-mcp-test@example.com",
        is_admin=True,
    )

    runtime_service.startup()
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            report: list[dict[str, Any]] = []
            tools_resp = await client.get("/api/v1/tools")
            tools_payload = tools_resp.json()
            mcp_tools = [
                item for item in tools_payload.get("data", []) if item.get("transport_protocol") == "mcp" and item.get("tool_origin") == "external"
            ]
            report.append(
                {
                    "endpoint": "GET /api/v1/tools",
                    "status": tools_resp.status_code,
                    "total": tools_payload.get("total"),
                    "mcp_names": [item.get("name") for item in mcp_tools],
                }
            )

            for item in mcp_tools:
                tool_name = item["name"]
                detail_resp = await client.get(f"/api/v1/tools/{tool_name}")
                detail_payload = detail_resp.json()
                exec_resp = await client.post(f"/api/v1/tools/{tool_name}/execute", json={"parameters": PAYLOADS.get(tool_name, {})})
                exec_payload = exec_resp.json()
                data_preview = None
                if isinstance(exec_payload.get("data"), dict):
                    data_preview = list(exec_payload["data"].keys())[:8]
                report.append(
                    {
                        "tool": tool_name,
                        "detail_status": detail_resp.status_code,
                        "detail_ok": detail_payload.get("success"),
                        "parameters_count": len((detail_payload.get("data") or {}).get("parameters", [])),
                        "exec_status": exec_resp.status_code,
                        "success": exec_payload.get("success"),
                        "error": exec_payload.get("error"),
                        "error_code": exec_payload.get("error_code"),
                        "data_preview": data_preview,
                    }
                )

            print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        app.dependency_overrides.clear()
        await runtime_service.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

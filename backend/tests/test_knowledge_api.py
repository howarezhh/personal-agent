from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from backend.api import knowledge
from backend.api.dependencies import get_current_user_id


class FakeKnowledgeApplicationService:
    def list_knowledge_bases(self, *, user_id: str):
        assert user_id == "user-1"
        items = [
            SimpleNamespace(
                to_dict=lambda: {
                    "knowledge_base_id": "kb-1",
                    "user_id": "user-1",
                    "name": "Alpha",
                    "description": None,
                    "is_default": True,
                    "is_active": True,
                    "created_at": "2026-03-10T00:00:00+00:00",
                    "updated_at": "2026-03-10T00:00:00+00:00",
                }
            )
        ]
        return items, 1


@pytest.mark.asyncio
async def test_get_knowledge_bases_returns_success(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(knowledge, "get_knowledge_application_service", lambda: FakeKnowledgeApplicationService())

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    try:
        response = await client.get("/api/v1/knowledge/bases")
        assert response.status_code == 200

        payload = response.json()
        assert payload["data"]["total"] == 1
        assert payload["data"]["knowledge_bases"][0]["knowledge_base_id"] == "kb-1"
        assert payload["data"]["knowledge_bases"][0]["is_default"] is True
    finally:
        await client.aclose()

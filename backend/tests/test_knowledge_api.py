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

    def get_user_knowledge_base(self, *, user_id: str, knowledge_base_id: str):
        return SimpleNamespace(knowledge_base_id=knowledge_base_id, name="Alpha")

    def ensure_default_for_user(self, *, user_id: str):
        return SimpleNamespace(knowledge_base_id="kb-1", name="Alpha")


class FakeDocumentApplicationService:
    async def create_document_upload(self, *, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        return SimpleNamespace(file_id="doc-1")

    async def process_uploaded_document(self, file_id: str, request_id: str | None = None):
        return {"success": True}

    def get_document_status(self, *, document_id: str, user_id: str):
        return {
            "document_id": document_id,
            "file_name": "ok.txt",
            "file_type": "text",
            "file_size": 5,
            "chunk_count": 0,
            "upload_time": "2026-03-10T00:00:00+00:00",
            "user_id": user_id,
            "knowledge_base_id": "kb-1",
            "knowledge_base_name": "Alpha",
            "status": "processing",
            "processing_stage": "parsing",
            "processing_progress": 20,
            "error_message": None,
        }

    async def upload_documents_batch(self, *, user_id: str, upload_files, knowledge_base_id: str | None, request_id: str | None = None):
        return {
            "total": len(upload_files),
            "success_count": 1,
            "failed_count": len(upload_files) - 1,
            "results": [
                {
                    "file_name": upload_files[0].filename,
                    "success": True,
                    "document": {
                        "document_id": "doc-1",
                        "file_name": upload_files[0].filename,
                        "file_type": "text",
                        "file_size": 5,
                        "chunk_count": 1,
                        "upload_time": "2026-03-10T00:00:00+00:00",
                        "user_id": user_id,
                        "knowledge_base_id": knowledge_base_id,
                        "knowledge_base_name": "Alpha",
                        "status": "completed",
                    },
                    "error": None,
                },
                {
                    "file_name": upload_files[1].filename,
                    "success": False,
                    "document": None,
                    "error": "parse failed",
                },
            ],
        }


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


@pytest.mark.asyncio
async def test_upload_documents_batch_returns_per_file_results(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(knowledge, "get_knowledge_application_service", lambda: FakeKnowledgeApplicationService())
    monkeypatch.setattr(knowledge, "get_document_application_service", lambda: FakeDocumentApplicationService())

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    try:
        response = await client.post(
            "/api/v1/knowledge/upload/batch",
            data={"knowledge_base_id": "kb-1"},
            files=[
                ("files", ("ok.txt", b"hello", "text/plain")),
                ("files", ("broken.txt", b"bad", "text/plain")),
            ],
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["data"]["total"] == 2
        assert payload["data"]["success_count"] == 1
        assert payload["data"]["failed_count"] == 1
        assert payload["data"]["results"][0]["document"]["file_name"] == "ok.txt"
        assert payload["data"]["results"][1]["error"] == "parse failed"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_upload_document_returns_pending_status_snapshot(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(knowledge, "get_knowledge_application_service", lambda: FakeKnowledgeApplicationService())
    monkeypatch.setattr(knowledge, "get_document_application_service", lambda: FakeDocumentApplicationService())

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    try:
        response = await client.post(
            "/api/v1/knowledge/upload",
            data={"knowledge_base_id": "kb-1"},
            files={"file": ("ok.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 200

        payload = response.json()
        assert payload["data"]["document_id"] == "doc-1"
        assert payload["data"]["status"] == "processing"
        assert payload["data"]["processing_stage"] == "parsing"
        assert payload["data"]["processing_progress"] == 20
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_document_status_returns_progress(monkeypatch):
    app = FastAPI()
    app.include_router(knowledge.router)
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    monkeypatch.setattr(knowledge, "get_document_application_service", lambda: FakeDocumentApplicationService())

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")

    try:
        response = await client.get("/api/v1/knowledge/documents/doc-1/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["status"] == "processing"
        assert payload["data"]["processing_stage"] == "parsing"
        assert payload["data"]["processing_progress"] == 20
    finally:
        await client.aclose()

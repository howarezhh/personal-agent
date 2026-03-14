from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from backend.application.services.document_application_service import DocumentApplicationService
from backend.models.file import FileCreate, FileType, ProcessingStatus, File
from backend.services.knowledge_base_service import get_file_type


class FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str | None = None):
        self.filename = filename
        self._content = content
        self.content_type = content_type

    async def read(self):
        return self._content


class FakeFileRepository:
    def __init__(self):
        self.file = None
        self.files_by_id = {}
        self.deleted_file_ids = []

    def _set_file(self, file):
        self.file = file
        self.files_by_id[file.file_id] = file

    def create_file(self, file_create: FileCreate):
        self._set_file(file_create.to_file())
        return self.file

    def get_file_by_id(self, file_id: str):
        return self.files_by_id.get(file_id)

    def delete_file(self, file_id: str):
        file = self.files_by_id.pop(file_id, None)
        if file is None:
            return False
        self.deleted_file_ids.append(file_id)
        if self.file and self.file.file_id == file_id:
            self.file = None
        return True


class FakeStorageGateway:
    def __init__(self):
        self.saved = {}
        self.deleted = []

    def build_path(self, upload_dir: str, file_id: str, original_filename: str) -> str:
        return f"{upload_dir}/{file_id}-{original_filename}"

    def write_bytes(self, path: str, content: bytes) -> None:
        self.saved[path] = content

    def delete(self, path: str) -> None:
        self.deleted.append(path)
        self.saved.pop(path, None)


class FakeProcessorAgent:
    def __init__(self, repo: FakeFileRepository, *, success: bool, error: str | None = None):
        self.repo = repo
        self.success = success
        self.error = error

    async def process_file(self, file_id: str):
        current_file = self.repo.get_file_by_id(file_id)
        if self.success:
            updated_file = replace(
                current_file,
                processing_status=ProcessingStatus.COMPLETED,
                processed_at=datetime.utcnow(),
                chunk_count=2,
                summary="summary",
                metadata={**(current_file.metadata or {}), "chunk_count": 2},
            )
            self.repo._set_file(updated_file)
            return {"success": True, "chunk_count": 2, "summary": "summary"}

        updated_file = replace(
            current_file,
            processing_status=ProcessingStatus.FAILED,
            error_message=self.error,
        )
        self.repo._set_file(updated_file)
        return {"success": False, "error": self.error}


class FakeKnowledgeBaseRepository:
    def get_by_id_for_user(self, knowledge_base_id: str, user_id: str):
        return SimpleNamespace(knowledge_base_id=knowledge_base_id, name="Knowledge Base")


def test_file_from_dict_restores_serialized_database_record():
    restored = File.from_dict(
        {
            "file_id": "file-1",
            "user_id": "user-1",
            "conversation_id": None,
            "original_filename": "demo.txt",
            "file_type": "text",
            "file_size": 3,
            "storage_path": "uploads/demo.txt",
            "processing_status": "completed",
            "created_at": "2026-03-10T10:00:00",
            "updated_at": "2026-03-10T10:05:00",
            "processed_at": "2026-03-10T10:06:00",
            "chunk_count": 1,
            "summary": "done",
            "metadata": '{"knowledge_managed": true}',
        }
    )

    assert restored.file_type is FileType.TEXT
    assert restored.processing_status is ProcessingStatus.COMPLETED
    assert restored.created_at.isoformat() == "2026-03-10T10:00:00"
    assert restored.metadata == {"knowledge_managed": True}


def test_get_file_type_rejects_legacy_doc_uploads():
    assert get_file_type("legacy.doc") is FileType.OTHER


@pytest.mark.asyncio
async def test_document_application_service_cleans_up_failed_upload(monkeypatch):
    file_repo = FakeFileRepository()
    storage_gateway = FakeStorageGateway()
    cleanup_calls = []
    monkeypatch.setattr(
        "backend.application.services.document_application_service.delete_file_knowledge_data",
        lambda **kwargs: cleanup_calls.append(kwargs) or {"chunk_count": 0, "vector_count": 0, "chunk_ids": []},
    )
    service = DocumentApplicationService(
        file_repo=file_repo,
        knowledge_base_repo=FakeKnowledgeBaseRepository(),
        storage_gateway=storage_gateway,
        processor_agent=FakeProcessorAgent(file_repo, success=False, error="parse failed"),
    )

    with pytest.raises(RuntimeError, match="parse failed"):
        await service.upload_document(
            user_id="user-1",
            upload_file=FakeUploadFile("broken.docx", b"bad-data"),
            knowledge_base_id="kb-1",
            request_id="req-1",
        )

    assert cleanup_calls
    assert file_repo.file is None
    assert len(file_repo.deleted_file_ids) == 1
    assert len(storage_gateway.deleted) == 1
    assert not storage_gateway.saved


@pytest.mark.asyncio
async def test_document_application_service_returns_processed_document():
    storage_gateway = FakeStorageGateway()
    file_repo = FakeFileRepository()
    service = DocumentApplicationService(
        file_repo=file_repo,
        knowledge_base_repo=FakeKnowledgeBaseRepository(),
        storage_gateway=storage_gateway,
        processor_agent=FakeProcessorAgent(file_repo, success=True),
    )

    result = await service.upload_document(
        user_id="user-1",
        upload_file=FakeUploadFile("notes.txt", b"hello knowledge base"),
        knowledge_base_id="kb-1",
        request_id="req-1",
    )

    assert result["document_id"] == file_repo.file.file_id
    assert result["knowledge_base_id"] == "kb-1"
    assert result["chunk_count"] == 2
    assert result["status"] == "completed"
    assert result["process_result"]["success"] is True
    assert storage_gateway.saved


@pytest.mark.asyncio
async def test_document_application_service_batch_upload_returns_mixed_results(monkeypatch):
    file_repo = FakeFileRepository()
    storage_gateway = FakeStorageGateway()
    monkeypatch.setattr(
        "backend.application.services.document_application_service.delete_file_knowledge_data",
        lambda **kwargs: {"chunk_count": 0, "vector_count": 0, "chunk_ids": []},
    )
    service = DocumentApplicationService(
        file_repo=file_repo,
        knowledge_base_repo=FakeKnowledgeBaseRepository(),
        storage_gateway=storage_gateway,
        processor_agent=FakeProcessorAgent(file_repo, success=True),
    )

    async def fake_upload_document(*, user_id: str, upload_file, knowledge_base_id: str | None, request_id: str | None = None):
        if upload_file.filename == "broken.txt":
            raise RuntimeError("parse failed")
        return {
            "document_id": f"doc-{upload_file.filename}",
            "file_name": upload_file.filename,
            "file_type": "text",
            "file_size": len(await upload_file.read()),
            "chunk_count": 1,
            "upload_time": "2026-03-14T00:00:00",
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_name": "Knowledge Base",
            "status": "completed",
        }

    monkeypatch.setattr(service, "upload_document", fake_upload_document)

    result = await service.upload_documents_batch(
        user_id="user-1",
        upload_files=[
            FakeUploadFile("ok.txt", b"hello"),
            FakeUploadFile("broken.txt", b"bad"),
        ],
        knowledge_base_id="kb-1",
        request_id="req-1",
    )

    assert result["total"] == 2
    assert result["success_count"] == 1
    assert result["failed_count"] == 1
    assert result["results"][0]["success"] is True
    assert result["results"][1]["success"] is False


@pytest.mark.asyncio
async def test_document_application_service_rejects_mime_type_mismatch():
    file_repo = FakeFileRepository()
    service = DocumentApplicationService(
        file_repo=file_repo,
        knowledge_base_repo=FakeKnowledgeBaseRepository(),
        storage_gateway=FakeStorageGateway(),
        processor_agent=FakeProcessorAgent(file_repo, success=True),
    )

    with pytest.raises(ValueError, match="MIME 类型与扩展名不匹配"):
        await service.upload_document(
            user_id="user-1",
            upload_file=FakeUploadFile("notes.txt", b"hello knowledge base", content_type="application/pdf"),
            knowledge_base_id="kb-1",
            request_id="req-1",
        )

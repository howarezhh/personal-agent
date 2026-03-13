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

    def create_file(self, file_create: FileCreate):
        self.file = file_create.to_file()
        return self.file

    def get_file_by_id(self, file_id: str):
        if self.file and self.file.file_id == file_id:
            return self.file
        return None


class FakeStorageGateway:
    def __init__(self):
        self.saved = {}

    def build_path(self, upload_dir: str, file_id: str, original_filename: str) -> str:
        return f"{upload_dir}/{file_id}-{original_filename}"

    def write_bytes(self, path: str, content: bytes) -> None:
        self.saved[path] = content


class FakeProcessorAgent:
    def __init__(self, repo: FakeFileRepository, *, success: bool, error: str | None = None):
        self.repo = repo
        self.success = success
        self.error = error

    async def process_file(self, file_id: str):
        if self.success:
            self.repo.file = replace(
                self.repo.file,
                processing_status=ProcessingStatus.COMPLETED,
                processed_at=datetime.utcnow(),
                chunk_count=2,
                summary="summary",
                metadata={**(self.repo.file.metadata or {}), "chunk_count": 2},
            )
            return {"success": True, "chunk_count": 2, "summary": "summary"}

        self.repo.file = replace(
            self.repo.file,
            processing_status=ProcessingStatus.FAILED,
            error_message=self.error,
        )
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
async def test_document_application_service_raises_when_processing_fails():
    file_repo = FakeFileRepository()
    service = DocumentApplicationService(
        file_repo=file_repo,
        knowledge_base_repo=FakeKnowledgeBaseRepository(),
        storage_gateway=FakeStorageGateway(),
        processor_agent=FakeProcessorAgent(file_repo, success=False, error="parse failed"),
    )

    with pytest.raises(RuntimeError, match="parse failed"):
        await service.upload_document(
            user_id="user-1",
            upload_file=FakeUploadFile("broken.docx", b"bad-data"),
            knowledge_base_id="kb-1",
            request_id="req-1",
        )

    assert file_repo.file is not None
    assert file_repo.file.processing_status is ProcessingStatus.FAILED


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

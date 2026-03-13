"""Local file storage gateway."""

from __future__ import annotations

import os


class LocalFileStorageGateway:
    def __init__(self):
        pass

    def build_path(self, upload_dir: str, file_id: str, original_filename: str) -> str:
        _, file_ext = os.path.splitext(original_filename)
        return os.path.join(upload_dir, f"{file_id}{file_ext}")

    def write_bytes(self, path: str, content: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as buffer:
            buffer.write(content)

    def delete(self, path: str) -> None:
        if self.exists(path):
            os.remove(path)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

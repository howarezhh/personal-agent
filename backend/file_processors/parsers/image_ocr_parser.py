from __future__ import annotations

from pathlib import Path
from typing import List

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class ImageOCRParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Image file does not exist: {path}")

        text = self._extract_text_from_image(path)
        metadata = {
            "parser": "image_ocr",
            "has_text": bool(text),
            "empty_content": not bool(text),
            "ocr_enabled": True,
        }
        return self.finalize_parsed_content(file_path, ParsedContent(text=text, metadata=metadata, images=[{"image_path": str(path)}]))

    def _extract_text_from_image(self, path: Path) -> str:
        try:
            from PIL import Image
            import pytesseract
        except ImportError as exc:
            raise ImportError("Image OCR requires Pillow and pytesseract") from exc

        with Image.open(path) as image:
            text = pytesseract.image_to_string(image)
        return self._clean_text_value(text, self._get_text_cleaning_profile(path.suffix.lower()))

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]

    def get_supported_extensions(self) -> List[str]:
        return [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]

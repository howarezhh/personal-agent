from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import shutil
from typing import Any

import numpy as np


def _normalize_ocr_text(text: Any) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip()).strip()


@lru_cache(maxsize=1)
def _get_rapidocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _extract_rapidocr_text(result: Any) -> str:
    if not result:
        return ""

    texts: list[str] = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            candidate = item[1]
            if isinstance(candidate, (list, tuple)) and candidate:
                candidate = candidate[0]
            normalized = _normalize_ocr_text(candidate)
            if normalized:
                texts.append(normalized)
    return "\n".join(texts).strip()


def get_available_ocr_engines() -> list[str]:
    engines: list[str] = []

    try:
        _get_rapidocr_engine()
        engines.append("rapidocr")
    except Exception:
        pass

    try:
        import pytesseract

        if shutil.which(getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") or "tesseract"):
            engines.append("pytesseract")
    except Exception:
        pass

    return engines


def get_ocr_runtime_hint() -> str:
    engines = get_available_ocr_engines()
    if engines:
        return f"available={','.join(engines)}"
    return "未检测到可用 OCR 运行时；请安装 rapidocr_onnxruntime 或配置 Tesseract 可执行文件"


def extract_text_from_image(image: Any) -> tuple[str, str]:
    try:
        rapid_ocr = _get_rapidocr_engine()
        result, _elapsed = rapid_ocr(np.asarray(image))
        rapid_text = _extract_rapidocr_text(result)
        if rapid_text:
            return rapid_text, "rapidocr"
    except Exception:
        pass

    try:
        import pytesseract

        tesseract_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract") or "tesseract"
        if shutil.which(tesseract_cmd):
            text = _normalize_ocr_text(pytesseract.image_to_string(image))
            if text:
                return text, "pytesseract"
    except Exception:
        pass

    raise RuntimeError(get_ocr_runtime_hint())


def extract_text_from_image_path(path: str | Path) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        return extract_text_from_image(image)

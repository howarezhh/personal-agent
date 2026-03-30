from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from backend.models.file import FileType


@dataclass(frozen=True)
class DocumentFormatSpec:
    """统一描述一种文档格式能力。

    这份注册表同时承担以下映射关系的单一事实源：
    - 扩展名 -> FileType
    - 扩展名 -> MIME 白名单
    - 扩展名 -> Parser key
    - 扩展名 -> 配置文档中的 supported 列表
    """

    name: str
    file_type: FileType
    parser_key: str | None
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...] = ()
    upload_enabled: bool = True
    knowledge_enabled: bool = True
    agent_visible: bool = True

    def matches_filename(self, filename: str | None) -> bool:
        """按完整文件名匹配，兼容 `.gitignore`、`.env` 这类隐藏文件。"""
        normalized_name = Path(filename or "").name.strip().lower()
        if not normalized_name:
            return False
        return any(normalized_name.endswith(extension) for extension in self.extensions)


def _build_spec(
    name: str,
    file_type: FileType,
    parser_key: str | None,
    extensions: Iterable[str],
    mime_types: Iterable[str] = (),
    *,
    upload_enabled: bool = True,
    knowledge_enabled: bool = True,
    agent_visible: bool = True,
) -> DocumentFormatSpec:
    return DocumentFormatSpec(
        name=name,
        file_type=file_type,
        parser_key=parser_key,
        extensions=tuple(str(extension).lower() for extension in extensions),
        mime_types=tuple(str(mime_type).strip().lower() for mime_type in mime_types if str(mime_type).strip()),
        upload_enabled=upload_enabled,
        knowledge_enabled=knowledge_enabled,
        agent_visible=agent_visible,
    )


_DOCUMENT_FORMATS: tuple[DocumentFormatSpec, ...] = (
    _build_spec("pdf", FileType.PDF, "pdf", [".pdf"], ["application/pdf"]),
    _build_spec(
        "docx",
        FileType.DOCX,
        "word",
        [".docx"],
        [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/zip",
        ],
    ),
    _build_spec(
        "doc",
        FileType.OTHER,
        None,
        [".doc"],
        ["application/msword"],
        upload_enabled=False,
        knowledge_enabled=False,
        agent_visible=False,
    ),
    _build_spec(
        "pptx",
        FileType.PPTX,
        "pptx",
        [".pptx"],
        [
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/zip",
        ],
    ),
    _build_spec(
        "xlsx",
        FileType.XLSX,
        "excel",
        [".xlsx"],
        [
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/zip",
        ],
    ),
    _build_spec(
        "xls",
        FileType.XLSX,
        "excel",
        [".xls"],
        ["application/vnd.ms-excel"],
    ),
    _build_spec(
        "csv",
        FileType.TABULAR,
        "tabular",
        [".csv"],
        ["text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"],
    ),
    _build_spec(
        "tsv",
        FileType.TABULAR,
        "tabular",
        [".tsv"],
        ["text/tab-separated-values", "text/plain"],
    ),
    _build_spec("html", FileType.HTML, "html", [".html"], ["text/html", "application/xhtml+xml"]),
    _build_spec("htm", FileType.HTML, "html", [".htm"], ["text/html", "application/xhtml+xml"]),
    _build_spec(
        "svg",
        FileType.XML,
        "text",
        [".svg"],
        ["image/svg+xml", "application/xml", "text/xml", "text/plain"],
    ),
    _build_spec("txt", FileType.TEXT, "text", [".txt"], ["text/plain"]),
    _build_spec("rst", FileType.TEXT, "text", [".rst"], ["text/plain"]),
    _build_spec("log", FileType.TEXT, "text", [".log"], ["text/plain"]),
    _build_spec("md", FileType.MARKDOWN, "text", [".md"], ["text/markdown", "text/plain"]),
    _build_spec("markdown", FileType.MARKDOWN, "text", [".markdown"], ["text/markdown", "text/plain"]),
    _build_spec("json", FileType.JSON, "text", [".json"], ["application/json", "text/plain"]),
    _build_spec("xml", FileType.XML, "text", [".xml"], ["application/xml", "text/xml", "text/plain"]),
    _build_spec("png", FileType.IMAGE, "image", [".png"], ["image/png"]),
    _build_spec("jpg", FileType.IMAGE, "image", [".jpg"], ["image/jpeg"]),
    _build_spec("jpeg", FileType.IMAGE, "image", [".jpeg"], ["image/jpeg"]),
    _build_spec("gif", FileType.IMAGE, "image", [".gif"], ["image/gif"]),
    _build_spec("bmp", FileType.IMAGE, "image", [".bmp"], ["image/bmp"]),
    _build_spec("webp", FileType.IMAGE, "image", [".webp"], ["image/webp"]),
)


_CODE_EXTENSION_SPECS = [
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".bat",
    ".ps1",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    ".css",
    ".scss",
    ".less",
    ".vue",
    ".gitignore",
]

_COMMON_CODE_MIME_TYPES = (
    "text/plain",
    "text/x-python",
    "application/javascript",
    "text/javascript",
    "text/typescript",
    "application/x-sh",
    "text/x-shellscript",
    "text/css",
    "application/sql",
)

_DOCUMENT_FORMATS += tuple(
    _build_spec(extension.lstrip("."), FileType.CODE, "text", [extension], _COMMON_CODE_MIME_TYPES)
    for extension in _CODE_EXTENSION_SPECS
)

_DOCUMENT_FORMATS_BY_LENGTH = tuple(
    sorted(_DOCUMENT_FORMATS, key=lambda item: max(len(extension) for extension in item.extensions), reverse=True)
)


def iter_document_formats() -> tuple[DocumentFormatSpec, ...]:
    return _DOCUMENT_FORMATS


def get_document_format_spec(filename: str | None) -> Optional[DocumentFormatSpec]:
    for spec in _DOCUMENT_FORMATS_BY_LENGTH:
        if spec.matches_filename(filename):
            return spec
    return None


def get_file_type_for_filename(filename: str | None) -> FileType:
    spec = get_document_format_spec(filename)
    if spec is None:
        return FileType.OTHER
    return spec.file_type


def normalize_search_file_type(file_type: str | None) -> str | None:
    """把 API 层传入的文件类型条件统一归一到检索元数据值域。

    中文说明：知识库检索的 `file_type` 过滤必须和入库元数据完全一致。
    例如上传 `csv` 最终会落到 `tabular`，上传 `xls` 会落到 `xlsx`。
    这里直接把搜索条件统一映射到最终存储值，删除旧的“调用方自己猜存储值”逻辑。
    """
    normalized_value = str(file_type or "").strip().lower()
    if not normalized_value:
        return None

    if normalized_value in {item.value for item in FileType}:
        return normalized_value

    synthetic_filename = f"query.{normalized_value.lstrip('.')}"
    resolved_file_type = get_file_type_for_filename(synthetic_filename)
    if resolved_file_type == FileType.OTHER:
        return normalized_value
    return resolved_file_type.value


def get_parser_key_for_file_type(file_type: FileType | str | None) -> str | None:
    normalized_file_type = file_type.value if isinstance(file_type, FileType) else str(file_type or "").lower()
    parser_keys = {
        spec.parser_key
        for spec in _DOCUMENT_FORMATS
        if spec.parser_key and spec.file_type.value == normalized_file_type
    }
    if not parser_keys:
        return None
    if len(parser_keys) > 1:
        raise ValueError(f"FileType {normalized_file_type} 对应了多个 parser_key: {sorted(parser_keys)}")
    return next(iter(parser_keys))


def get_allowed_mime_types_for_filename(filename: str | None) -> set[str]:
    spec = get_document_format_spec(filename)
    return set(spec.mime_types) if spec else set()


def list_upload_allowed_format_names() -> list[str]:
    return [spec.name for spec in _DOCUMENT_FORMATS if spec.upload_enabled]


def list_knowledge_supported_format_names() -> list[str]:
    return [spec.name for spec in _DOCUMENT_FORMATS if spec.knowledge_enabled]


def list_agent_supported_format_names() -> list[str]:
    return [spec.name for spec in _DOCUMENT_FORMATS if spec.agent_visible and spec.parser_key is not None]

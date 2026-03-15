
from typing import List
from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class WordParser(BaseParser):
    def __init__(self):
        super().__init__()

    async def parse(self, file_path: str) -> ParsedContent:
        try:
            from docx import Document
        except ImportError:
            raise ImportError("python-docx is not installed. Please install it: pip install python-docx")

        try:
            doc = Document(file_path)

            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text)

            full_text = "\n\n".join(paragraphs)

            tables_data = []
            for table_idx, table in enumerate(doc.tables):
                table_data = {
                    "table_index": table_idx + 1,
                    "rows": []
                }

                table_lines = [f"[表格 {table_idx + 1}]"]

                for row_index, row in enumerate(table.rows, start=1):
                    row_data = [cell.text.strip() for cell in row.cells]
                    table_data["rows"].append(row_data)

                    row_values = [cell for cell in row_data if cell]
                    if row_values:
                        table_lines.append(f"第{row_index}行 | " + " | ".join(row_values))

                tables_data.append(table_data)

                if len(table_lines) > 1:
                    full_text += "\n\n" + "\n".join(table_lines)

            # 提取元数据
            metadata = {
                "paragraph_count": len(paragraphs),
                "table_count": len(tables_data),
                "parser": "python-docx"
            }

            try:
                core_properties = doc.core_properties
                if core_properties.title:
                    metadata["title"] = core_properties.title
                if core_properties.author:
                    metadata["author"] = core_properties.author
                if core_properties.subject:
                    metadata["subject"] = core_properties.subject
                if core_properties.created:
                    metadata["created"] = core_properties.created.isoformat()
                if core_properties.modified:
                    metadata["modified"] = core_properties.modified.isoformat()
            except Exception as e:
                self.logger.warning(f"Failed to extract document properties: {str(e)}")

            return self.finalize_parsed_content(
                file_path,
                ParsedContent(
                    text=full_text,
                    metadata=metadata,
                    tables=tables_data if tables_data else None
                )
            )

        except Exception as e:
            self.logger.error(f"Failed to parse Word document: {str(e)}")
            raise

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in ['.docx']

    def get_supported_extensions(self) -> List[str]:
        return ['.docx']

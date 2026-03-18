
from __future__ import annotations

import os
from typing import List

from backend.file_processors.parsers.base_parser import BaseParser, ParsedContent


class ExcelParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError(
                "pandas is not installed. Please install it: pip install pandas openpyxl"
            ) from exc

        try:
            excel_file = pd.ExcelFile(file_path)
            all_text: List[str] = []
            tables_data = []
            cell_profile = self._get_text_cleaning_profile(".xlsx")

            for sheet_name in excel_file.sheet_names:
                dataframe = pd.read_excel(file_path, sheet_name=sheet_name).fillna("")
                cleaned_sheet_name = self._clean_text_value(sheet_name, cell_profile)
                columns = [
                    self._clean_text_value(column, cell_profile) or f"column_{index + 1}"
                    for index, column in enumerate(dataframe.columns.tolist())
                ]

                rows = []
                sheet_lines = [f"[工作表] {cleaned_sheet_name}"]
                for row_index, row in enumerate(dataframe.itertuples(index=False, name=None), start=1):
                    cleaned_row = [self._clean_text_value(value, cell_profile) for value in row]
                    rows.append(cleaned_row)

                    row_values = [
                        f"{column}: {value}"
                        for column, value in zip(columns, cleaned_row)
                        if value
                    ]
                    if row_values:
                        sheet_lines.append(f"第{row_index}行 | " + " | ".join(row_values))

                all_text.append("\n".join(sheet_lines))
                tables_data.append(
                    {
                        "sheet_name": cleaned_sheet_name,
                        "rows": rows,
                        "columns": columns,
                    }
                )

            full_text = "\n\n".join(all_text)
            metadata = {
                "sheet_count": len(excel_file.sheet_names),
                "sheet_names": excel_file.sheet_names,
                "parser": "pandas",
            }

            return self.finalize_parsed_content(
                file_path,
                ParsedContent(text=full_text, metadata=metadata, tables=tables_data),
            )

        except Exception as exc:
            self.logger.error(f"Failed to parse Excel: {str(exc)}")
            raise

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [".xlsx", ".xls"]

    def get_supported_extensions(self) -> List[str]:
        return [".xlsx", ".xls"]


class TextParser(BaseParser):
    async def parse(self, file_path: str) -> ParsedContent:
        try:
            encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
            text = None
            used_encoding = None

            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as file_obj:
                        text = file_obj.read()
                    used_encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue

            if text is None:
                raise ValueError("无法使用常见编码读取文件")

            file_ext = os.path.splitext(file_path)[1].lower()
            metadata = {
                "encoding": used_encoding,
                "file_extension": file_ext,
                "line_count": len(text.split("\n")),
                "char_count": len(text),
                "parser": "text",
            }

            return self.finalize_parsed_content(
                file_path,
                ParsedContent(text=text, metadata=metadata),
            )

        except Exception as exc:
            self.logger.error(f"Failed to parse text file: {str(exc)}")
            raise

    def supports(self, file_extension: str) -> bool:
        return file_extension.lower() in [
            ".txt",
            ".md",
            ".markdown",
            ".json",
            ".xml",
            ".csv",
            ".tsv",
            ".log",
            ".rst",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".go",
            ".rs",
            ".sh",
            ".bash",
            ".bat",
            ".ps1",
            ".sql",
            ".css",
            ".scss",
            ".less",
            ".vue",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".conf",
            ".env",
            ".properties",
        ]

    def get_supported_extensions(self) -> List[str]:
        return [
            ".txt",
            ".md",
            ".markdown",
            ".json",
            ".xml",
            ".csv",
            ".tsv",
            ".log",
            ".rst",
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".go",
            ".rs",
            ".sh",
            ".bash",
            ".bat",
            ".ps1",
            ".sql",
            ".css",
            ".scss",
            ".less",
            ".vue",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".conf",
            ".env",
            ".properties",
        ]

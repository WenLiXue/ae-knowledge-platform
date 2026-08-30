"""文本文件提取：供本地上传和飞书 Drive 附件复用。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


SUPPORTED_FILE_EXTENSIONS = {".pdf", ".docx", ".xlsx"}


def extract_file_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    if suffix == ".docx":
        document = Document(BytesIO(data))
        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            parts.extend("\t".join(cell.text for cell in row.cells) for row in table.rows)
        return "\n".join(parts)
    if suffix == ".xlsx":
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in workbook.worksheets:
            parts.append(f"# {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value) for value in row]
                if any(value.strip() for value in values):
                    parts.append("\t".join(values))
        workbook.close()
        return "\n".join(parts)
    raise ValueError(f"unsupported file type: {suffix}")

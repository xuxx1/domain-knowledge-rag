"""文档解析服务：把上传文件解析为纯文本

支持：pdf / docx / txt / md
"""

from pathlib import Path

from .. import config


class ParseError(Exception):
    pass


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        return "\n".join(pages)
    except Exception as e:
        raise ParseError(f"PDF 解析失败：{e}") from e


def _parse_docx(path: Path) -> str:
    from docx import Document as DocxDocument

    try:
        doc = DocxDocument(str(path))
        # 段落 + 表格单元格文本
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        return "\n".join(parts)
    except Exception as e:
        raise ParseError(f"Word 解析失败：{e}") from e


def _parse_text(path: Path) -> str:
    for encoding in ("utf-8", "gbk", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ParseError("无法识别文件编码（尝试过 utf-8/gbk/utf-16）")


PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "txt": _parse_text,
    "md": _parse_text,
}


def parse_file(path: Path) -> str:
    """按扩展名选择解析器，返回纯文本"""
    ext = path.suffix.lstrip(".").lower()
    parser = PARSERS.get(ext)
    if not parser:
        raise ParseError(f"不支持的文件类型：{ext}（支持 pdf/docx/txt/md）")
    text = parser(path)
    # 规范空白：连续 3+ 空行压成 1 行
    lines = [ln.rstrip() for ln in text.splitlines()]
    cleaned: list[str] = []
    blank = 0
    for ln in lines:
        if ln.strip():
            cleaned.append(ln)
            blank = 0
        else:
            blank += 1
            if blank <= 1:
                cleaned.append("")
    return "\n".join(cleaned).strip()


ALLOWED_EXTENSIONS = set(PARSERS.keys())


def file_type_of(filename: str) -> str:
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ParseError(f"不支持的文件类型：.{ext}（支持 pdf/docx/txt/md）")
    return ext

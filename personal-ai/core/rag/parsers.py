"""PDF、DOCX、Markdown 和纯文本解析，统一输出带来源位置的结构块。"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path


class ParseError(ValueError):
    pass


class ResourceLimitError(ParseError):
    pass


@dataclass(frozen=True)
class ParsedBlock:
    section: str
    content: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass(frozen=True)
class ParseResult:
    blocks: list[ParsedBlock]
    needs_ocr: bool = False


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("文本文件不是有效的 UTF-8 或 GB18030 编码")


def parse_plain_text(path: Path, settings) -> ParseResult:
    text = _read_text(path)
    blocks: list[ParsedBlock] = []
    for match in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        content = match.group(0).strip()
        if content:
            blocks.append(ParsedBlock("正文", content, char_start=match.start(), char_end=match.end()))
    return ParseResult(blocks)


def parse_markdown(path: Path, settings) -> ParseResult:
    text = _read_text(path)
    headings: list[str] = []
    blocks: list[ParsedBlock] = []
    buffer: list[str] = []
    buffer_start: int | None = None
    offset = 0

    def flush(end: int) -> None:
        nonlocal buffer, buffer_start
        content = "".join(buffer).strip()
        if content:
            blocks.append(
                ParsedBlock(
                    " > ".join(headings) or "正文",
                    content,
                    char_start=buffer_start,
                    char_end=end,
                )
            )
        buffer = []
        buffer_start = None

    for line in text.splitlines(keepends=True):
        heading = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if heading:
            flush(offset)
            level = len(heading.group(1))
            headings[:] = headings[: level - 1]
            headings.append(heading.group(2).strip())
        else:
            if buffer_start is None and line.strip():
                buffer_start = offset
            buffer.append(line)
        offset += len(line)
    flush(len(text))
    return ParseResult(blocks)


def _validate_docx_archive(path: Path, max_uncompressed_bytes: int) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 10_000:
                raise ResourceLimitError("DOCX 内部条目数量超过限制")
            if sum(info.file_size for info in infos) > max_uncompressed_bytes:
                raise ResourceLimitError("DOCX 解压后大小超过限制")
            if "[Content_Types].xml" not in archive.namelist() or "word/document.xml" not in archive.namelist():
                raise ParseError("文件不是有效的 DOCX")
    except zipfile.BadZipFile as exc:
        raise ParseError("DOCX 文件损坏") from exc


def parse_docx(path: Path, settings) -> ParseResult:
    _validate_docx_archive(path, settings.docx_max_uncompressed_bytes)
    from docx import Document as WordDocument

    try:
        document = WordDocument(path)
    except Exception as exc:
        raise ParseError(f"DOCX 解析失败：{exc}") from exc

    headings: list[str] = []
    blocks: list[ParsedBlock] = []
    for paragraph in document.paragraphs:
        content = paragraph.text.strip()
        if not content:
            continue
        match = re.match(r"Heading\s+([1-4])", paragraph.style.name or "", re.IGNORECASE)
        if match:
            level = int(match.group(1))
            headings[:] = headings[: level - 1]
            headings.append(content)
            continue
        blocks.append(ParsedBlock(" > ".join(headings) or "正文", content))
    return ParseResult(blocks)


def _pdf_is_text_poor(texts: list[str], settings) -> bool:
    total_chars = sum(len(text.strip()) for text in texts)
    text_pages = sum(1 for text in texts if text.strip())
    ratio = text_pages / max(1, len(texts))
    return total_chars < settings.pdf_needs_ocr_min_chars or ratio < settings.pdf_needs_ocr_min_text_page_ratio


def parse_pdf(path: Path, settings) -> ParseResult:
    from pypdf import PdfReader

    try:
        reader = PdfReader(path)
        if reader.is_encrypted and reader.decrypt("") == 0:
            raise ParseError("PDF 已加密，无法解析")
        if len(reader.pages) > settings.file_max_pages:
            raise ResourceLimitError(f"PDF 页数超过限制：{settings.file_max_pages}")
        texts = [(page.extract_text() or "") for page in reader.pages]
    except (ParseError, ResourceLimitError):
        raise
    except Exception as exc:
        raise ParseError(f"PDF 解析失败：{exc}") from exc

    if _pdf_is_text_poor(texts, settings):
        try:
            import pdfplumber

            with pdfplumber.open(path) as pdf:
                if len(pdf.pages) > settings.file_max_pages:
                    raise ResourceLimitError(f"PDF 页数超过限制：{settings.file_max_pages}")
                fallback = [(page.extract_text() or "") for page in pdf.pages]
            if sum(len(text) for text in fallback) > sum(len(text) for text in texts):
                texts = fallback
        except ResourceLimitError:
            raise
        except Exception:
            pass

    if _pdf_is_text_poor(texts, settings):
        return ParseResult([], needs_ocr=True)
    blocks = [
        ParsedBlock(f"第 {index} 页", text.strip(), page_start=index, page_end=index)
        for index, text in enumerate(texts, start=1)
        if text.strip()
    ]
    return ParseResult(blocks)


PARSERS = {
    ".md": parse_markdown,
    ".txt": parse_plain_text,
    ".docx": parse_docx,
    ".pdf": parse_pdf,
}


def parse_document(path: Path, extension: str, settings) -> ParseResult:
    parser = PARSERS.get(extension.lower())
    if parser is None:
        raise ParseError(f"不支持的文件类型：{extension}")
    result = parser(path, settings)
    total_chars = sum(len(block.content) for block in result.blocks)
    if total_chars > settings.file_max_parsed_chars:
        raise ResourceLimitError(f"解析后文本超过限制：{settings.file_max_parsed_chars} 字符")
    return result

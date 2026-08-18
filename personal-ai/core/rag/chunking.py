"""按结构与完整句分块，同时满足字符数和 Embedding tokenizer 上限。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from core.rag.parsers import ParsedBlock, ResourceLimitError


@dataclass(frozen=True)
class ChunkDraft:
    section: str
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True)
class _Segment:
    text: str
    start: int
    end: int


def _sentence_segments(text: str) -> list[_Segment]:
    segments: list[_Segment] = []
    for match in re.finditer(r".+?(?:[。！？!?；;]+|\n+|$)", text, flags=re.DOTALL):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        leading = len(raw) - len(raw.lstrip())
        start = match.start() + leading
        segments.append(_Segment(stripped, start, start + len(stripped)))
    return segments


def _largest_prefix(text: str, max_chars: int, max_tokens: int, count_tokens: Callable[[str], int]) -> int:
    high = min(len(text), max_chars)
    low = 1
    best = 0
    while low <= high:
        middle = (low + high) // 2
        if count_tokens(text[:middle]) <= max_tokens:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best <= 0:
        raise ResourceLimitError("单个字符超过 Embedding tokenizer 上限")
    if best < len(text):
        boundary = max(text.rfind(mark, max(0, best * 2 // 3), best) for mark in " ，,、：:\t")
        if boundary > 0:
            best = boundary + 1
    return best


def _split_oversized(
    segment: _Segment,
    max_chars: int,
    max_tokens: int,
    count_tokens: Callable[[str], int],
) -> list[_Segment]:
    if len(segment.text) <= max_chars and count_tokens(segment.text) <= max_tokens:
        return [segment]
    pieces: list[_Segment] = []
    remaining = segment.text
    offset = segment.start
    while remaining:
        length = _largest_prefix(remaining, max_chars, max_tokens, count_tokens)
        piece = remaining[:length].strip()
        leading = len(remaining[:length]) - len(remaining[:length].lstrip())
        if piece:
            start = offset + leading
            pieces.append(_Segment(piece, start, start + len(piece)))
        offset += length
        remaining = remaining[length:]
    return pieces


def split_into_chunks(blocks: list[ParsedBlock], count_tokens: Callable[[str], int], settings) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    for block in blocks:
        segments: list[_Segment] = []
        for sentence in _sentence_segments(block.content):
            segments.extend(
                _split_oversized(
                    sentence,
                    settings.rag_chunk_max_chars,
                    settings.rag_chunk_max_tokens,
                    count_tokens,
                )
            )
        current: list[_Segment] = []
        has_new_content = False

        def emit() -> None:
            nonlocal current, has_new_content
            if not current or not has_new_content:
                return
            content = "".join(segment.text for segment in current)
            chunks.append(
                ChunkDraft(
                    section=block.section,
                    content=content,
                    page_start=block.page_start,
                    page_end=block.page_end,
                    char_start=(block.char_start + current[0].start) if block.char_start is not None else None,
                    char_end=(block.char_start + current[-1].end) if block.char_start is not None else None,
                )
            )
            overlap = max(0, settings.rag_chunk_overlap_sentences)
            current = current[-overlap:] if overlap else []
            has_new_content = False

        for segment in segments:
            candidate = "".join(item.text for item in [*current, segment])
            if current and (
                len(candidate) > settings.rag_chunk_max_chars
                or count_tokens(candidate) > settings.rag_chunk_max_tokens
            ):
                emit()
                while current:
                    candidate = "".join(item.text for item in [*current, segment])
                    if len(candidate) <= settings.rag_chunk_max_chars and count_tokens(candidate) <= settings.rag_chunk_max_tokens:
                        break
                    current = current[1:]
            current.append(segment)
            has_new_content = True
            candidate = "".join(item.text for item in current)
            if len(candidate) >= settings.rag_chunk_target_chars:
                emit()
        emit()
    if len(chunks) > settings.file_max_chunks:
        raise ResourceLimitError(f"分块数量超过限制：{settings.file_max_chunks}")
    return chunks

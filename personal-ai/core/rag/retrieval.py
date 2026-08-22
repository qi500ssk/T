"""SQLite 阶段的向量 + BM25 + RRF 混合检索。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from infrastructure.database import Document, DocumentChunk


jieba.setLogLevel(logging.WARNING)


_EXPLICIT_KNOWLEDGE_PATTERN = re.compile(
    r"(?:知识库|我上传的|上传的(?:资料|文档|文件|附件)|(?:简历|文档|资料|报告)(?:中|里|内|上)|"
    r"(?:根据|结合|查找|检索|查询)(?:这份|该|我的)?(?:资料|文档|文件|附件|简历|报告))",
    re.IGNORECASE,
)
_SIMPLE_CHAT_PATTERN = re.compile(
    r"^(?:你?好|嗨|hi|hello|谢谢|多谢|再见|早上好|中午好|下午好|晚上好)[!！。,.，?？]*$",
    re.IGNORECASE,
)
_CURRENT_INFO_PATTERN = re.compile(
    r"^(?=.{1,40}$)(?=.*(?:现在|当前|今天|明天))"
    r"(?=.*(?:几点|时间|日期|星期|天气|位置|地点)).*$"
)
_WRITE_ACTION_PATTERN = re.compile(
    r"^(?:(?:请|帮我|请帮我)?(?:写入|保存|记录)(?:一?条)?(?:笔记|文件|备忘))"
)


def should_retrieve_knowledge(query: str) -> bool:
    """轻量查询门控：只跳过明确无需个人资料库的请求。"""
    text = re.sub(r"\s+", "", query).strip()
    if not text:
        return False
    if _EXPLICIT_KNOWLEDGE_PATTERN.search(text) or re.search(
        r"\.(?:pdf|docx|txt|md)\b", text, re.IGNORECASE
    ):
        return True
    if (
        _SIMPLE_CHAT_PATTERN.fullmatch(text)
        or _CURRENT_INFO_PATTERN.fullmatch(text)
        or _WRITE_ACTION_PATTERN.match(text)
    ):
        return False
    expression = re.sub(
        r"^(?:(?:请帮我|帮我|请)?(?:计算一下|计算出?|算一下|算出?|求))",
        "",
        text,
    )
    expression = re.sub(r"(?:等于多少|是多少|的结果)?[?？。]*$", "", expression)
    if re.fullmatch(r"[0-9０-９+\-*/×÷%^().（）]+", expression) and re.search(
        r"[+\-*/×÷%^]", expression
    ):
        return False
    return True


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    document_id: str
    filename: str
    section: str
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int | None
    char_end: int | None
    chunk_index: int
    vector_score: float | None
    bm25_score: float | None
    rrf_score: float
    retrieval_rank: int


def tokenize_for_bm25(text: str) -> list[str]:
    return [
        token
        for raw in jieba.lcut(text)
        if (token := raw.strip().lower())
        and re.search(r"[a-z0-9\u4e00-\u9fff]", token, re.IGNORECASE)
    ]


def retrieve(
    session: Session,
    embedding_provider,
    query: str,
    settings,
    user_id: str = "default",
    final_limit: int | None = None,
    document_ids: list[str] | None = None,
) -> list[RetrievalResult]:
    query_builder = (
        session.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.user_id == user_id,
            Document.status == "indexed",
            Document.embedding_model == embedding_provider.model_name,
            Document.embedding_dim == embedding_provider.dimension,
        )
    )
    if document_ids:
        query_builder = query_builder.filter(Document.id.in_(document_ids))
    rows = query_builder.all()
    if not rows:
        return []

    query_vector = np.asarray(embedding_provider.embed_query(query), dtype=np.float32)
    matrix = np.asarray([chunk.embedding for chunk, _ in rows], dtype=np.float32)
    vector_scores = matrix @ query_vector
    vector_order = np.argsort(-vector_scores)[: settings.rag_vector_top_k].tolist()

    corpus = [tokenize_for_bm25(chunk.content) for chunk, _ in rows]
    query_tokens = tokenize_for_bm25(query)
    if query_tokens and any(corpus):
        bm25_scores = np.asarray(BM25Okapi(corpus).get_scores(query_tokens), dtype=np.float32)
        bm25_order = [
            index
            for index in np.argsort(-bm25_scores)[: settings.rag_bm25_top_k].tolist()
            if bm25_scores[index] > 0
        ]
    else:
        bm25_scores = np.zeros(len(rows), dtype=np.float32)
        bm25_order = []

    vector_rank = {index: rank for rank, index in enumerate(vector_order, start=1)}
    bm25_rank = {index: rank for rank, index in enumerate(bm25_order, start=1)}
    candidates: list[tuple[float, int]] = []
    for index in set(vector_order) | set(bm25_order):
        # 用户明确选择附件时，即使问题只是“总结一下”也应读取该文档；
        # 相似度阈值只用于全库检索，避免把无关资料带入普通聊天。
        if not document_ids and index in vector_rank and index not in bm25_rank:
            if float(vector_scores[index]) < settings.rag_min_vector_similarity:
                continue
        score = 0.0
        if index in vector_rank:
            score += 1.0 / (settings.rag_rrf_k + vector_rank[index])
        if index in bm25_rank:
            score += 1.0 / (settings.rag_rrf_k + bm25_rank[index])
        candidates.append((score, index))
    candidates.sort(
        key=lambda item: (item[0], float(vector_scores[item[1]])),
        reverse=True,
    )

    limit = final_limit if final_limit is not None else settings.rag_final_top_k
    results: list[RetrievalResult] = []
    for rank, (rrf_score, index) in enumerate(candidates[:limit], start=1):
        chunk, document = rows[index]
        results.append(
            RetrievalResult(
                chunk_id=chunk.id,
                document_id=document.id,
                filename=document.original_filename,
                section=chunk.section,
                content=chunk.content,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                chunk_index=chunk.chunk_index,
                vector_score=float(vector_scores[index]) if index in vector_rank else None,
                bm25_score=float(bm25_scores[index]) if index in bm25_rank else None,
                rrf_score=rrf_score,
                retrieval_rank=rank,
            )
        )
    return results

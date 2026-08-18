"""SQLite 阶段的向量 + BM25 + RRF 混合检索。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from infrastructure.database import Document, DocumentChunk


jieba.setLogLevel(logging.WARNING)


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
    return [token.strip().lower() for token in jieba.lcut(text) if token.strip()]


def retrieve(
    session: Session,
    embedding_provider,
    query: str,
    settings,
    user_id: str = "default",
    final_limit: int | None = None,
) -> list[RetrievalResult]:
    rows = (
        session.query(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .filter(
            Document.user_id == user_id,
            Document.status == "indexed",
            Document.embedding_model == embedding_provider.model_name,
            Document.embedding_dim == embedding_provider.dimension,
        )
        .all()
    )
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
        if index in vector_rank and index not in bm25_rank:
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

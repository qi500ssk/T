"""P2 固定知识库检索评测，运行在独立的 PostgreSQL 测试库。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# 评测库必须在导入应用模块前确定：默认使用 5433 隔离测试库。
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://personal_ai:personal_ai_test_local@localhost:5433/personal_ai_test",
)
if not os.environ["DATABASE_URL"].rstrip("/").endswith("/personal_ai_test"):
    raise RuntimeError("检索评测只允许连接 personal_ai_test 数据库")

from sqlalchemy.orm import Session  # noqa: E402

from core.rag.embedding import build_embedding_provider  # noqa: E402
from core.rag.chunking import split_into_chunks  # noqa: E402
from core.rag.parsers import parse_document  # noqa: E402
from core.rag.retrieval import retrieve  # noqa: E402
from infrastructure.config import settings  # noqa: E402
from infrastructure.database import Document, DocumentChunk, SessionLocal, init_db  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_DIR = ROOT / "tests" / "eval" / "documents"
CASE_FILE = ROOT / "tests" / "eval" / "rag_cases.json"


def reset_corpus(session: Session) -> None:
    session.query(DocumentChunk).delete()
    session.query(Document).delete()
    session.commit()


def build_corpus(session: Session, provider) -> None:
    for path in sorted(DOCUMENT_DIR.iterdir()):
        if path.suffix.lower() not in {".md", ".txt", ".docx", ".pdf"}:
            continue
        parsed = parse_document(path, path.suffix.lower(), settings)
        drafts = split_into_chunks(parsed.blocks, provider.count_tokens, settings)
        vectors = provider.embed_documents([draft.content for draft in drafts])
        data = path.read_bytes()
        document = Document(
            original_filename=path.name,
            stored_filename=path.name,
            mime_type="text/markdown" if path.suffix == ".md" else "text/plain",
            file_type=path.suffix.lower(),
            size_bytes=len(data),
            status="indexed",
            chunk_count=len(drafts),
            content_hash=hashlib.sha256(data).hexdigest(),
            embedding_model=provider.model_name,
            embedding_dim=provider.dimension,
        )
        session.add(document)
        session.flush()
        for index, (draft, vector) in enumerate(zip(drafts, vectors, strict=True)):
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    section=draft.section,
                    content=draft.content,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    char_start=draft.char_start,
                    char_end=draft.char_end,
                    embedding=vector,
                )
            )
    session.commit()


def main() -> None:
    provider = build_embedding_provider(settings)
    init_db()
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    ranks: list[int | None] = []
    keyword_hits = 0
    section_hits = 0
    failures: list[str] = []
    try:
        with SessionLocal() as session:
            reset_corpus(session)
            build_corpus(session, provider)
            for case in cases:
                results = retrieve(session, provider, case["question"], settings, final_limit=5)
                rank = next(
                    (
                        index
                        for index, result in enumerate(results, start=1)
                        if result.filename == case["expect_document"]
                    ),
                    None,
                )
                ranks.append(rank)
                expected_section = case.get("expect_section", "")
                if any(
                    result.filename == case["expect_document"]
                    and expected_section in result.section
                    for result in results
                ):
                    section_hits += 1
                keywords = case.get("expect_keywords", [])
                if any(
                    result.filename == case["expect_document"]
                    and all(keyword in result.content for keyword in keywords)
                    for result in results
                ):
                    keyword_hits += 1
                if rank is None:
                    returned = ", ".join(result.filename for result in results) or "无结果"
                    failures.append(f"- {case['question']} → {returned}")
    finally:
        provider.close()

    total = len(cases)
    recall_1 = sum(rank is not None and rank <= 1 for rank in ranks) / total
    recall_3 = sum(rank is not None and rank <= 3 for rank in ranks) / total
    recall_5 = sum(rank is not None and rank <= 5 for rank in ranks) / total
    mrr = sum(1 / rank for rank in ranks if rank is not None) / total
    print(f"Provider: {provider.model_name} ({provider.dimension}d)")
    print(f"Cases: {total}")
    print(f"Recall@1: {recall_1:.3f}")
    print(f"Recall@3: {recall_3:.3f}")
    print(f"Recall@5: {recall_5:.3f}")
    print(f"MRR: {mrr:.3f}")
    print(f"Section hit: {section_hits / total:.3f}")
    print(f"Keyword hit: {keyword_hits / total:.3f}")
    if failures:
        print("Failures:")
        print("\n".join(failures))


if __name__ == "__main__":
    main()

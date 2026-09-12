"""好友背景记忆：来源校验、草稿提取与有界召回。"""
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ConfigDict

from core.rag.retrieval import tokenize_for_bm25
from infrastructure.database import CharacterMemory, CharacterExtraction, Document, DocumentChunk, SessionLocal

PROMPT = Path(__file__).resolve().parents[2] / "prompts/memory/character.md"


class MemoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["personality", "experience", "relationship", "world"] = "experience"
    content: str = Field(min_length=1, max_length=1200)
    evidence_type: Literal["fact", "inference"] = "fact"
    is_core: bool = False
    known_to_character: bool = True
    time_label: str = Field(default="", max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=12)
    source_quote: str = Field(default="", max_length=500)


def fingerprint(content):
    return hashlib.sha256("".join(content.split()).encode()).hexdigest()


def memory_dict(row):
    return {name: getattr(row, name) for name in (
        "id", "agent_id", "kind", "content", "evidence_type", "is_core", "known_to_character",
        "time_label", "tags", "status", "document_id", "chunk_id", "source_name",
        "source_section", "source_quote", "extraction_id",
    )}


async def extract_document(job_id, character_name, provider, max_input_tokens):
    try:
        with SessionLocal() as session:
            job = session.get(CharacterExtraction, job_id)
            document = session.get(Document, job.document_id)
            if document is None:
                raise ValueError("原始资料已删除")
            agent_id, source_name = job.agent_id, document.original_filename
            chunks = [(row.id, row.section, row.content) for row in session.query(DocumentChunk).filter(
                DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index).all()]
            job.total = len(chunks)
            session.commit()
        from core.chat.context import estimate_tokens
        if not chunks or len(chunks) > 300:
            raise ValueError("每次支持 1–300 个资料片段，请将过长资料按章节导入")
        prompt = PROMPT.read_text(encoding="utf-8")
        # 全文逐段处理，超预算明确失败，绝不静默只处理 top-k 或截掉尾部。
        if any(estimate_tokens(prompt + text + character_name) > max_input_tokens for _, _, text in chunks):
            raise ValueError("资料片段超过所选聊天模型上下文预算，请调整分块或模型配置")
        async with asyncio.timeout(1200):
            for chunk_id, section, text in chunks:
                with SessionLocal() as session:
                    current = session.get(CharacterExtraction, job_id)
                    if current is None or current.status != "running":
                        return
                async with asyncio.timeout(120):
                    result = await provider.complete([
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps({"target_character": character_name, "section": section, "source": text}, ensure_ascii=False)},
                    ], temperature=0.0)
                raw = result.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                payload = json.loads(raw)
                if not isinstance(payload, dict) or not isinstance(payload.get("memories"), list) or len(payload["memories"]) > 12:
                    raise ValueError("模型返回的记忆格式无效")
                with SessionLocal() as session:
                    current = session.get(CharacterExtraction, job_id)
                    chunk = session.get(DocumentChunk, chunk_id)
                    if current is None or current.status != "running" or chunk is None or chunk.content != text:
                        raise ValueError("提取期间原始资料已改变")
                    for item in payload["memories"]:
                        try:
                            draft = MemoryDraft.model_validate(item)
                            if not draft.content.strip() or not draft.source_quote.strip() or draft.source_quote not in text or any(len(tag) > 60 for tag in draft.tags):
                                raise ValueError("来源引用无法核对")
                        except (ValueError, TypeError):
                            current.rejected += 1
                            continue
                        digest = fingerprint(draft.content)
                        if session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                                CharacterMemory.fingerprint == digest, CharacterMemory.status.in_(["draft", "active"])).first():
                            continue
                        session.add(CharacterMemory(agent_id=agent_id, document_id=current.document_id,
                            chunk_id=chunk_id, source_name=source_name, source_section=section,
                            extraction_id=job_id, fingerprint=digest, **draft.model_dump()))
                        session.flush()
                    current.processed += 1
                    session.commit()
        with SessionLocal() as session:
            job = session.get(CharacterExtraction, job_id)
            if job and job.status == "running":
                job.status = "completed"
                session.commit()
    except asyncio.CancelledError:
        _fail_job(job_id, "提取已中断，已生成的草稿仍可查看；可重新提取剩余资料")
        raise
    except Exception as error:
        # 不回显云端响应（可能含密钥或原始私人资料）。
        detail = str(error) if type(error) is ValueError and str(error) in {
            "原始资料已删除", "每次支持 1–300 个资料片段，请将过长资料按章节导入",
            "资料片段超过所选聊天模型上下文预算，请调整分块或模型配置", "模型返回的记忆格式无效", "提取期间原始资料已改变",
        } else "提取失败，请检查聊天模型连接；已生成草稿保留，可重新提取"
        _fail_job(job_id, detail)
    finally:
        await provider.close()


def _fail_job(job_id, error):
    with SessionLocal() as session:
        job = session.get(CharacterExtraction, job_id)
        if job:
            job.status, job.error = "failed", error
            session.commit()


def recall_character_memories(session, agent_id, query, provider=None, limit=16):
    if not agent_id:
        return []
    search = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
        CharacterMemory.status == "active", CharacterMemory.known_to_character.is_(True))
    rows = search.all()
    terms = set(tokenize_for_bm25(query))
    scored = {}
    for row in rows:
        overlap = len(terms & set(tokenize_for_bm25(row.content + " " + " ".join(row.tags))))
        if row.is_core or overlap:
            scored[row.id] = (100 if row.is_core else 0) + overlap
    if rows and provider is not None and provider.dimension > 0:
        try:
            vector = provider.embed_query(query)
            distance = CharacterMemory.embedding.cosine_distance(vector).label("distance")
            matches = search.filter(CharacterMemory.embedding_model == provider.model_name,
                CharacterMemory.embedding_dim == provider.dimension, CharacterMemory.embedding.is_not(None)).add_columns(distance).order_by(distance).limit(limit).all()
            for row, value in matches:
                if value is not None and 1 - value >= getattr(provider, "min_similarity", 0.3):
                    scored[row.id] = scored.get(row.id, 0) + 1 - value
        except Exception:
            pass  # 语义不可用时继续使用核心及词法记忆。
    rows.sort(key=lambda row: (scored.get(row.id, -1), row.updated_at), reverse=True)
    return [row for row in rows if row.id in scored][:limit]

"""L2 世界事实：覆盖每个片段，有界提取，可续跑，不直接注入角色记忆。"""
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from core.memory.graph import MemoryGraphData, build_memory_graph
from core.memory.identity import rules_for, aliases_for, project_graph
from core.memory.organize import organize_document, organization_snapshot
from infrastructure.database import DocumentChunk, DocumentGraphChunk, WorldFact, SessionLocal, CharacterMemory, PersonResolution, GraphOrganization

PROMPT = Path(__file__).resolve().parents[2] / "prompts/memory/document_graph.md"


def clear_document_graph(session, document_id):
    """Clear derived graph only; retain source and detach existing character drafts."""
    ids = session.query(WorldFact.id).filter(WorldFact.document_id == document_id)
    linked = session.query(CharacterMemory).filter(CharacterMemory.world_fact_id.in_(ids))
    linked.filter(CharacterMemory.status == "active").update({"status": "draft"}, synchronize_session=False)
    linked.update({"world_fact_id": None}, synchronize_session=False)
    for model in (WorldFact, DocumentGraphChunk, PersonResolution, GraphOrganization):
        session.query(model).filter(model.document_id == document_id).delete(synchronize_session=False)


class DocumentFact(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=1200)
    source_quote: str = Field(min_length=1, max_length=500)
    time_label: str = Field(default="", max_length=200)
    evidence_type: Literal["fact", "inference"] = "fact"
    graph: MemoryGraphData = Field(default_factory=MemoryGraphData)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def validate_fact(fact, source):
    quotes = [fact.source_quote, *(r.quote for r in fact.graph.relationships), *(r.quote for r in fact.graph.event_links)]
    if fact.graph.start or fact.graph.end:
        quotes.append(fact.graph.time_quote)
    if any(not quote or quote not in source for quote in quotes):
        raise ValueError("原文依据不匹配")


def document_graph_snapshot(session, document):
    chunks = session.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index).all()
    stored = {row.chunk_id: row for row in session.query(DocumentGraphChunk).filter(DocumentGraphChunk.document_id == document.id)}
    coverage, facts = [], []
    records = {}
    for fact in session.query(WorldFact).filter(WorldFact.document_id == document.id):
        records.setdefault(fact.chunk_id, []).append(fact)
    for chunk in chunks:
        row = stored.get(chunk.id)
        current = row is not None and row.source_hash == digest(chunk.content)
        coverage.append({"chunk_id": chunk.id, "index": chunk.chunk_index, "section": chunk.section,
                         "status": row.status if current else "pending", "error": row.error if current else "",
                         "fact_count": len(records.get(chunk.id, [])) if current else 0})
        if current:
            for fact in records.get(chunk.id, []):
                if fact.status == "rejected" or fact.source_hash != digest(chunk.content):
                    continue
                item = {key: getattr(fact, key) for key in ("id", "content", "source_quote", "time_label", "evidence_type", "graph", "status")}
                facts.append({**item, "document_id": document.id, "chunk_id": chunk.id,
                              "source_name": document.original_filename, "source_section": chunk.section,
                              "kind": "experience", "is_core": False, "known_to_character": False, "tags": []})
    organization = organization_snapshot(session, document.id)
    filtered = [f for f in facts if f["status"] == "filtered"]
    facts = [f for f in facts if f["status"] != "filtered"]
    rules = rules_for(session, document.id)
    aliases = aliases_for(rules)
    graph = build_memory_graph([SimpleNamespace(**{**item, "event_group": organization["groups"].get(item["id"]), "graph": project_graph(item["graph"], aliases)}) for item in facts], None)
    return {**graph, "organization": organization, "filtered_facts": filtered, "identity_rules": rules, "facts": facts, "coverage": coverage, "total": len(chunks),
            "completed": sum(c["status"] == "completed" for c in coverage),
            "partial": sum(c["status"] == "partial" for c in coverage),
            "failed": sum(c["status"] == "failed" for c in coverage)}


async def extract_document_graph(document_id, provider, input_budget, *, organize=False, organize_only=False):
    from core.chat.context import estimate_tokens
    cancelled = False
    try:
        with SessionLocal() as session:
            chunks = [(c.id, c.content, c.section) for c in session.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index)]
        prompt = PROMPT.read_text(encoding="utf-8")
        if organize_only:
            chunks = []
        async with asyncio.timeout(1200):
            for chunk_id, source, section in chunks:
                await asyncio.sleep(0)  # Let stop requests interrupt even an immediate provider.
                with SessionLocal() as session:
                    if session.get(DocumentChunk, chunk_id) is None:
                        continue
                    row = session.get(DocumentGraphChunk, chunk_id)
                    if row and row.source_hash == digest(source) and row.status == "completed":
                        continue
                    if row is None:
                        row = DocumentGraphChunk(chunk_id=chunk_id, document_id=document_id, source_hash=digest(source))
                        session.add(row)
                    if row.source_hash != digest(source):
                        session.query(WorldFact).filter(WorldFact.chunk_id == chunk_id).update({"status": "stale"})
                    row.source_hash, row.status, row.error = digest(source), "running", ""
                    session.commit()
                try:
                    # 只送当前片段，全文遍历由程序执行，不让模型只挑主角或重要章节。
                    with SessionLocal() as session:
                        identity_rules = rules_for(session, document_id)
                    relevant_rules = [r for r in identity_rules if r["name"] in source or r["target"] in source]
                    user_text = json.dumps({"section": section, "source": source,
                        "confirmed_identities": relevant_rules}, ensure_ascii=False)
                    if estimate_tokens(prompt + user_text) > input_budget:
                        raise ValueError("片段超出模型上下文预算，请调整分块或模型设置")
                    async with asyncio.timeout(120):
                        result = await provider.complete([{"role": "system", "content": prompt},
                            {"role": "user", "content": user_text}], temperature=0)
                    raw = result.strip()
                    if raw.startswith("```"):
                        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list) or len(payload["facts"]) > 60:
                        raise ValueError("模型返回格式无效或单片段事实过多，请重试或减小分块")
                    accepted, rejected = [], 0
                    for item in payload["facts"]:
                        try:
                            fact = DocumentFact.model_validate(item)
                            validate_fact(fact, source)
                            value = fact.model_dump(mode="json")
                            value.update(id=digest(chunk_id + fact.content + fact.source_quote)[:32], status="draft")
                            accepted.append(value)
                        except (ValueError, TypeError):
                            rejected += 1
                    with SessionLocal() as session:
                        row = session.get(DocumentGraphChunk, chunk_id)
                        chunk = session.get(DocumentChunk, chunk_id)
                        if not row or not chunk or chunk.content != source:
                            continue
                        # 保留已经审核/补充的内容；同一事实不为不同角色复制。
                        for value in accepted:
                            existing = session.get(WorldFact, value["id"])
                            if existing is None:
                                session.add(WorldFact(document_id=document_id, chunk_id=chunk_id,
                                    source_hash=digest(source), **value))
                            elif existing.source_hash != digest(source):
                                for key, field in value.items():
                                    setattr(existing, key, field)
                                existing.source_hash = digest(source)
                        row.status = "completed" if payload.get("complete") is True and not rejected else "partial"
                        row.error = "" if row.status == "completed" else f"有 {rejected} 条依据不匹配，或模型报告尚未提取完整；可核对后重试"
                        session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    with SessionLocal() as session:
                        row = session.get(DocumentGraphChunk, chunk_id)
                        if row:
                            row.status = "failed"
                            row.error = str(exc) if type(exc) is ValueError else "提取失败，请检查模型连接或响应格式后重试"
                            session.commit()
        if organize:
            await organize_document(document_id, provider, input_budget)
    except asyncio.CancelledError:
        cancelled = True
        raise
    except TimeoutError:
        pass  # 剩余片段保留 pending，下次从未完成位置续跑。
    finally:
        with SessionLocal() as session:
            session.query(DocumentGraphChunk).filter(DocumentGraphChunk.document_id == document_id,
                DocumentGraphChunk.status == "running").update({"status": "paused" if cancelled else "failed", "error": "已停止，可继续未完成片段" if cancelled else "提取中断，可继续未完成片段"})
            session.commit()
        try:
            async with asyncio.timeout(5):
                await provider.close()
        except Exception:
            pass

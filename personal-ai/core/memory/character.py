"""L3 角色背景记忆：来源校验、草稿提取与有界召回。"""
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal
from types import SimpleNamespace

from pydantic import BaseModel, Field, ConfigDict

from core.rag.retrieval import tokenize_for_bm25
from core.memory.graph import MemoryGraphData, graph_data
from core.memory.identity import rules_for, aliases_for, project_graph
from core.memory.organize import organization_snapshot
from core.memory.builder import Perspective
from infrastructure.database import CharacterMemory, CharacterExtraction, Document, DocumentChunk, WorldFact, SessionLocal

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
    graph: MemoryGraphData = Field(default_factory=MemoryGraphData)
    perspective: Perspective = Field(default_factory=Perspective)


def fingerprint(content):
    return hashlib.sha256("".join(content.split()).encode()).hexdigest()


def memory_dict(row):
    return {name: getattr(row, name) for name in (
        "id", "agent_id", "kind", "content", "evidence_type", "is_core", "known_to_character",
        "time_label", "tags", "status", "document_id", "chunk_id", "source_name",
        "source_section", "source_quote", "extraction_id", "graph", "world_fact_id", "perspective",
    )}


def resolve_character_memories(session, rows):
    """只投影此角色已引用的有效事实，绝不沿世界图谱无限扩展。"""
    fact_ids = {row.world_fact_id for row in rows if row.world_fact_id}
    facts = {fact.id: fact for fact in session.query(WorldFact).filter(WorldFact.id.in_(fact_ids))} if fact_ids else {}
    result = []
    identity_maps = {}
    event_groups = {}
    memory_ids = {row.world_fact_id: row.id for row in rows if row.world_fact_id}
    for row in rows:
        if not row.world_fact_id:
            if not row.perspective.get("story_character_id"):
                result.append(row)
            continue
        fact = facts.get(row.world_fact_id)
        chunk = session.get(DocumentChunk, fact.chunk_id) if fact else None
        if not fact or fact.status != "active" or not chunk:
            continue
        from core.memory.world import digest
        if fact.source_hash != digest(chunk.content) or row.perspective.get("knowledge", "unknown") == "unknown":
            continue
        if row.perspective.get("story_character_id"):
            evidence_chunks = row.perspective.get("source_chunks", [])
            if any((source := session.get(DocumentChunk, item["id"])) is None or digest(source.content) != item["hash"] for item in evidence_chunks):
                continue
            # Structured imports carry a restricted, user-confirmed viewpoint.
            # Do not replace its evidence/people with omniscient world facts.
            fields = {column.name: getattr(row, column.name) for column in CharacterMemory.__table__.columns}
            fields["graph"] = graph_data(row)
            result.append(SimpleNamespace(**fields))
            continue
        fields = {column.name: getattr(row, column.name) for column in CharacterMemory.__table__.columns}
        if fact.document_id not in identity_maps:
            identity_maps[fact.document_id] = aliases_for(rules_for(session, fact.document_id))
            event_groups[fact.document_id] = organization_snapshot(session, fact.document_id)["groups"]
        data = project_graph(graph_data(fact), identity_maps[fact.document_id])
        # 世界摘要不能覆盖角色自己的有限视角。
        data.update(summary=row.content[:240], importance=row.perspective.get("importance", 3),
                    importance_reason=row.perspective.get("importance_reason", ""))
        document = session.get(Document, fact.document_id)
        fields.update(graph=data, event_group=memory_ids.get(event_groups[fact.document_id].get(fact.id)), time_label=fact.time_label, source_quote=fact.source_quote,
                      document_id=fact.document_id, chunk_id=fact.chunk_id,
                      source_name=document.original_filename if document else "世界事实引用", source_section=chunk.section)
        result.append(SimpleNamespace(**fields))
    known_events = {graph_data(row)["event"] for row in result if row.status == "active" and row.known_to_character}
    for row in result:
        if row.world_fact_id:
            row.graph["event_links"] = [link for link in row.graph["event_links"] if link["event"] in known_events]
    return result


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
                    previous = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                        CharacterMemory.status.in_(["draft", "active"])).order_by(CharacterMemory.created_at.desc()).limit(24).all()
                    catalog = list(dict.fromkeys(graph_data(row)["event"] for row in previous if graph_data(row)["event"]))[:24]
                request_text = json.dumps({"target_character": character_name, "section": section,
                    "source": text, "known_events": catalog}, ensure_ascii=False)
                if estimate_tokens(prompt + request_text) > max_input_tokens:
                    # 当前原文优先，目录只是辅助，不能挤掉原文。
                    request_text = json.dumps({"target_character": character_name, "section": section, "source": text}, ensure_ascii=False)
                if estimate_tokens(prompt + request_text) > max_input_tokens:
                    raise ValueError("资料片段超过所选聊天模型上下文预算，请调整分块或模型配置")
                async with asyncio.timeout(120):
                    result = await provider.complete([
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": request_text},
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
                            if any(not relation.quote or relation.quote not in text for relation in draft.graph.relationships):
                                raise ValueError("关系来源无法核对")
                            if any(link.quote not in text for link in draft.graph.event_links):
                                raise ValueError("事件关系来源无法核对")
                            if (draft.graph.start or draft.graph.end) and (not draft.graph.time_quote or draft.graph.time_quote not in text):
                                raise ValueError("时间来源无法核对")
                        except (ValueError, TypeError):
                            current.rejected += 1
                            continue
                        digest = fingerprint(draft.content)
                        if session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                                CharacterMemory.fingerprint == digest, CharacterMemory.status.in_(["draft", "active"])).first():
                            continue
                        session.add(CharacterMemory(agent_id=agent_id, document_id=current.document_id,
                            chunk_id=chunk_id, source_name=source_name, source_section=section,
                            extraction_id=job_id, fingerprint=digest, **draft.model_dump(mode="json")))
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
    if not agent_id or limit <= 0:
        return []
    search = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
        CharacterMemory.status == "active", CharacterMemory.known_to_character.is_(True))
    rows = resolve_character_memories(session, search.all())
    terms = set(tokenize_for_bm25(query))
    scored = {}
    for row in rows:
        data = graph_data(row)
        searchable = row.content + " " + " ".join(row.tags + data["people"]) + " " + row.time_label + " " + data["event"]
        searchable += " " + " ".join(" ".join((rel["subject"], rel["predicate"], rel["object"])) for rel in data["relationships"])
        overlap = len(terms & set(tokenize_for_bm25(searchable)))
        if overlap:
            scored[row.id] = float(overlap)
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
    # 当前问题的相关性先于重要性；常驻核心最多两条，避免挤占事件。
    rank = lambda row: (scored.get(row.id, 0), graph_data(row)["importance"], row.updated_at, row.id)
    relevant = sorted([row for row in rows if row.id in scored], key=rank, reverse=True)
    result = relevant[:max(1, limit - 4)]
    core = sorted([row for row in rows if row.is_core and row not in result], key=rank, reverse=True)[:2]
    result.extend(core)
    # 只补充两条与最相关事件直接关联的记录，不沿整张网无限扩散。
    titles = {graph_data(row)["event"] for row in relevant[:3]} - {""}
    linked_titles = {link["event"] for row in relevant[:3] for link in graph_data(row)["event_links"]}
    neighbors = [row for row in rows if row not in result and (
        graph_data(row)["event"] in linked_titles or
        any(link["event"] in titles for link in graph_data(row)["event_links"]))]
    result.extend(sorted(neighbors, key=rank, reverse=True)[:2])
    for row in relevant:
        if row not in result:
            result.append(row)
    return result[:limit]

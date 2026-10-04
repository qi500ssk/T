"""L3 角色背景记忆：来源校验与有界召回。"""
import hashlib
from typing import Literal
from types import SimpleNamespace

from pydantic import BaseModel, Field, ConfigDict

from core.rag.retrieval import tokenize_for_bm25
from core.memory.metadata import MemoryMetadata, memory_metadata
from core.memory.identity import rules_for, aliases_for, project_graph
from core.memory.perspective import Perspective
from infrastructure.database import CharacterMemory, Document, DocumentChunk, WorldFact



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
    graph: MemoryMetadata = Field(default_factory=MemoryMetadata)
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
        from core.memory.evidence import digest
        if fact.source_hash != digest(chunk.content) or row.perspective.get("knowledge", "unknown") == "unknown":
            continue
        if row.perspective.get("story_character_id"):
            evidence_chunks = row.perspective.get("source_chunks", [])
            if any((source := session.get(DocumentChunk, item["id"])) is None or digest(source.content) != item["hash"] for item in evidence_chunks):
                continue
            # Structured imports carry a restricted, user-confirmed viewpoint.
            # Do not replace its evidence/people with omniscient world facts.
            fields = {column.name: getattr(row, column.name) for column in CharacterMemory.__table__.columns}
            fields["graph"] = memory_metadata(row)
            result.append(SimpleNamespace(**fields))
            continue
        fields = {column.name: getattr(row, column.name) for column in CharacterMemory.__table__.columns}
        if fact.document_id not in identity_maps:
            identity_maps[fact.document_id] = aliases_for(rules_for(session, fact.document_id))
        data = project_graph(memory_metadata(fact), identity_maps[fact.document_id])
        # 世界摘要不能覆盖角色自己的有限视角。
        data.update(summary=row.content[:240], importance=row.perspective.get("importance", 3),
                    importance_reason=row.perspective.get("importance_reason", ""))
        document = session.get(Document, fact.document_id)
        fields.update(graph=data, time_label=fact.time_label, source_quote=fact.source_quote,
                      document_id=fact.document_id, chunk_id=fact.chunk_id,
                      source_name=document.original_filename if document else "世界事实引用", source_section=chunk.section)
        result.append(SimpleNamespace(**fields))
    known_events = {memory_metadata(row)["event"] for row in result if row.status == "active" and row.known_to_character}
    for row in result:
        if row.world_fact_id:
            row.graph["event_links"] = [link for link in row.graph["event_links"] if link["event"] in known_events]
    return result


def recall_character_memories(session, agent_id, query, provider=None, limit=16):
    if not agent_id or limit <= 0:
        return []
    search = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
        CharacterMemory.status == "active", CharacterMemory.known_to_character.is_(True))
    rows = resolve_character_memories(session, search.all())
    terms = set(tokenize_for_bm25(query))
    scored = {}
    for row in rows:
        data = memory_metadata(row)
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
    rank = lambda row: (scored.get(row.id, 0), memory_metadata(row)["importance"], row.updated_at, row.id)
    relevant = sorted([row for row in rows if row.id in scored], key=rank, reverse=True)
    result = relevant[:max(1, limit - 4)]
    core = sorted([row for row in rows if row.is_core and row not in result], key=rank, reverse=True)[:2]
    result.extend(core)
    # 只补充两条与最相关事件直接关联的记录，不沿整张网无限扩散。
    titles = {memory_metadata(row)["event"] for row in relevant[:3]} - {""}
    linked_titles = {link["event"] for row in relevant[:3] for link in memory_metadata(row)["event_links"]}
    neighbors = [row for row in rows if row not in result and (
        memory_metadata(row)["event"] in linked_titles or
        any(link["event"] in titles for link in memory_metadata(row)["event_links"]))]
    result.extend(sorted(neighbors, key=rank, reverse=True)[:2])
    for row in relevant:
        if row not in result:
            result.append(row)
    return result[:limit]

"""整份文档图谱：与角色记忆分离，认证由应用中间件提供。"""
import asyncio
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from core.chat.gateway import build_provider
from core.memory.world import DocumentFact, digest, document_graph_snapshot, extract_document_graph, validate_fact, clear_document_graph
from core.memory.identity import rules_for, aliases_for
from core.memory.organize import remember_override
from core.memory.graph import UNRESOLVED_PEOPLE
from infrastructure.config import settings
from infrastructure.database import Document, DocumentChunk, DocumentGraphChunk, WorldFact, CharacterMemory, PersonResolution, SessionLocal

router = APIRouter(prefix="/api/documents", tags=["document-graph"])


def get_document(session, document_id):
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(404, "文档不存在")
    return document


@router.get("/{document_id}/graph")
def get_graph(document_id: str, request: Request):
    with SessionLocal() as session:
        snapshot = document_graph_snapshot(session, get_document(session, document_id))
    snapshot["running"] = f"document:{document_id}" in request.app.state.character_tasks
    return snapshot


@router.post("/{document_id}/graph/extract", status_code=202)
async def extract_graph(document_id: str, request: Request, organize_only: bool = False, reset: bool = False):
    tasks = request.app.state.character_tasks
    if tasks:
        raise HTTPException(409, "已有资料正在提取，请等待完成")
    if reset and organize_only:
        raise HTTPException(422, "重新生成不能仅整理旧图谱")
    if settings.llm_provider == "unconfigured":
        raise HTTPException(409, "请先配置聊天模型")
    with SessionLocal() as session:
        document = get_document(session, document_id)
        if document.status != "indexed" or not session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).count():
            raise HTTPException(422, "请先完成文档解析与索引")
    try:
        provider = build_provider(SimpleNamespace(**settings.model_dump()))
    except Exception:
        raise HTTPException(422, "聊天模型初始化失败") from None
    with SessionLocal() as session:
        if reset:
            clear_document_graph(session, document_id)
        first = session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).order_by(DocumentChunk.chunk_index).first()
        if first and session.get(DocumentGraphChunk, first.id) is None:
            session.add(DocumentGraphChunk(document_id=document_id, chunk_id=first.id, source_hash=digest(first.content)))
            session.commit()
    budget = max(512, settings.llm_context_window_tokens - settings.llm_max_output_tokens - 512)
    key = f"document:{document_id}"
    task = asyncio.create_task(extract_document_graph(document_id, provider, budget, organize=True, organize_only=organize_only))
    tasks[key] = task
    def finished(done):
        if tasks.get(key) is done:
            tasks.pop(key, None)
        if not done.cancelled():
            done.exception()  # Consume failures; chunk status records interruption.
    task.add_done_callback(finished)
    return {"ok": True}


@router.delete("/{document_id}/graph")
async def delete_graph(document_id: str, request: Request):
    if request.app.state.character_tasks:
        raise HTTPException(409, "请先停止图谱任务，或等待角色记忆构建完成")
    with SessionLocal() as session:
        get_document(session, document_id)
        clear_document_graph(session, document_id)
        session.commit()
    return {"ok": True}


@router.post("/{document_id}/graph/stop")
async def stop_graph(document_id: str, request: Request):
    with SessionLocal() as session:
        get_document(session, document_id)
    task = request.app.state.character_tasks.get(f"document:{document_id}")
    if task is None or task.done():
        return {"stopping": False}
    # Let a just-created extraction enter its try/finally before cancelling.
    await asyncio.sleep(0)
    if not task.cancelling():
        task.cancel()
    await asyncio.wait({task}, timeout=3)
    return {"stopping": not task.done()}


class IdentityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    target: str = Field(min_length=1, max_length=80)
    decision: Literal["same", "different"]


def invalidate_identity_memories(session, document_id):
    ids = session.query(WorldFact.id).filter(WorldFact.document_id == document_id)
    session.query(CharacterMemory).filter(CharacterMemory.world_fact_id.in_(ids),
        CharacterMemory.status == "active").update({"status": "draft"}, synchronize_session=False)


@router.post("/{document_id}/graph/identities")
async def decide_identity(document_id: str, body: IdentityDecision, request: Request):
    if request.app.state.character_tasks:
        raise HTTPException(409, "请先停止提取或等待记忆构建完成，再确认人物")
    if body.name in UNRESOLVED_PEOPLE or body.target in UNRESOLVED_PEOPLE:
        raise HTTPException(422, "代词不能设置整篇文档的归属，请按具体记录核对")
    with SessionLocal() as session:
        document = get_document(session, document_id)
        snapshot = document_graph_snapshot(session, document)
        names = set()
        for fact in [*snapshot["facts"], *snapshot.get("filtered_facts", [])]:
            names.update(fact["graph"].get("people", []))
            for relation in fact["graph"].get("relationships", []):
                names.update([relation["subject"], relation["object"]])
        if body.name not in names or body.target not in names:
            raise HTTPException(422, "请选择当前文档中已提取的人物称呼")
        rules = rules_for(session, document_id)
        value = body.model_dump()
        if any(all(r[k] == v for k, v in value.items()) for r in rules):
            existing = session.query(PersonResolution).filter_by(document_id=document_id, **value).first()
            if existing:
                remember_override(session, document_id, existing)
                session.commit()
            return {"ok": True}
        try:
            aliases_for([*rules, value])
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        if any(r["name"] == body.name and r["target"] == body.target for r in rules):
            raise HTTPException(409, "这两个称呼已有确认记录，请先撤销")
        session.add(PersonResolution(document_id=document_id, **value))
        invalidate_identity_memories(session, document_id)
        session.commit()
    return {"ok": True}


@router.delete("/{document_id}/graph/identities/{rule_id}")
async def undo_identity(document_id: str, rule_id: str, request: Request):
    if request.app.state.character_tasks:
        raise HTTPException(409, "请先停止提取或等待记忆构建完成")
    with SessionLocal() as session:
        get_document(session, document_id)
        rule = session.get(PersonResolution, rule_id)
        if rule is None or rule.document_id != document_id:
            raise HTTPException(404, "人物确认记录不存在")
        remember_override(session, document_id, rule)
        session.delete(rule)
        invalidate_identity_memories(session, document_id)
        session.commit()
    return {"ok": True}


class ReviewFact(DocumentFact):
    status: Literal["draft", "active", "rejected"] = "draft"


@router.patch("/{document_id}/graph/facts/{fact_id}")
def review_fact(document_id: str, fact_id: str, body: ReviewFact, request: Request):
    if f"document:{document_id}" in request.app.state.character_tasks:
        raise HTTPException(409, "请等待当前提取完成后审核")
    with SessionLocal() as session:
        get_document(session, document_id)
        row = session.get(WorldFact, fact_id)
        chunk = session.get(DocumentChunk, row.chunk_id) if row else None
        if not row or not chunk or row.document_id != document_id or chunk.document_id != document_id:
            raise HTTPException(404, "图谱记录不存在")
        if row.source_hash != digest(chunk.content):
            raise HTTPException(409, "原文已变化，请重新提取")
        try:
            validate_fact(body, chunk.content)
        except ValueError:
            raise HTTPException(422, "引用必须来自该记录所属原文片段") from None
        values = body.model_dump(mode="json")
        if any(getattr(row, key) != value for key, value in values.items() if key != "status"):
            session.query(CharacterMemory).filter(CharacterMemory.world_fact_id == row.id,
                CharacterMemory.status == "active").update({"status": "draft"})
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()
    return {"ok": True}


"""角色经历管理与来源可核对的异步提取。"""
from fastapi import APIRouter, HTTPException, Request
import anyio

from core.memory.character import MemoryDraft, fingerprint, memory_dict, resolve_character_memories
from infrastructure.database import CharacterMemory, CharacterExtraction, SessionLocal
from infrastructure.database import CandidateMemory, Memory, Conversation
from datetime import datetime, timezone

router = APIRouter(prefix="/api/characters", tags=["character-memory"])


def character(request, agent_id):
    profile = next((row for row in request.app.state.runtime_settings_store.snapshot()["agents"]["items"] if row["id"] == agent_id), None)
    if profile is None:
        raise HTTPException(404, "角色不存在")
    return profile


class SaveBody(MemoryDraft):
    status: str = "draft"


@router.get("/{agent_id}/memory-candidates")
def list_candidates(agent_id: str, request: Request):
    character(request, agent_id)
    with SessionLocal() as session:
        rows = session.query(CandidateMemory).filter(CandidateMemory.agent_id == agent_id,
            CandidateMemory.status == "pending", CandidateMemory.expires_at > datetime.now(timezone.utc)).order_by(CandidateMemory.updated_at.desc()).limit(200).all()
        return [{key:getattr(row,key) for key in ("id","content","kind","importance","confidence","source_conversation_id","expires_at")} for row in rows]


@router.post("/{agent_id}/memory-candidates/{candidate_id}/{action}")
def review_candidate(agent_id: str, candidate_id: str, action: str, request: Request):
    character(request, agent_id)
    if action not in {"confirm", "dismiss"}: raise HTTPException(422, "操作无效")
    with SessionLocal() as session:
        row = session.query(CandidateMemory).filter(CandidateMemory.id == candidate_id, CandidateMemory.agent_id == agent_id,
            CandidateMemory.status == "pending", CandidateMemory.expires_at > datetime.now(timezone.utc)).first()
        if row is None: raise HTTPException(404, "候选不存在或已过期")
        if action == "dismiss":
            row.status = "dismissed"; session.commit(); return {"ok":True}
        conversation = session.get(Conversation, row.source_conversation_id)
        if conversation is None or conversation.agent_id != agent_id: raise HTTPException(409, "来源对话已失效")
        if session.query(Memory).filter_by(user_id=row.user_id,scope_type="agent",scope_key=agent_id,normalized_key=row.normalized_key).first():
            raise HTTPException(409, "已存在同主题记忆，请在长期记忆列表中核对，候选不会覆盖它")
        from core.memory.conversation import MemoryCandidate, save_memories
        count = save_memories(session,[MemoryCandidate(row.normalized_key,row.kind,row.content,row.importance,1.0,"agent")],
            row.user_id,conversation.id,1,0,request.app.state.embedding_provider,agent_id=agent_id)
        if not count: raise HTTPException(409, "候选未写入，可能已有重复记忆")
        row.status = "confirmed"; session.commit()
        return {"ok":True}


@router.get("/{agent_id}/memories")
def list_memories(agent_id: str, request: Request):
    character(request, agent_id)
    with SessionLocal() as session:
        rows = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id).order_by(CharacterMemory.created_at.desc()).all()
        jobs = session.query(CharacterExtraction).filter(CharacterExtraction.agent_id == agent_id).order_by(CharacterExtraction.created_at.desc()).limit(10).all()
        projected = {row.id: row for row in resolve_character_memories(session, rows)}
        return {"memories": [{**memory_dict(projected.get(row.id, row)), "source_available": (not row.world_fact_id and not row.perspective.get("story_character_id")) or row.id in projected} for row in rows],
            "jobs": [{key: getattr(job, key) for key in ("id", "document_id", "status", "total", "processed", "rejected", "error")} for job in jobs]}


@router.post("/{agent_id}/memories", status_code=201)
async def create(agent_id: str, body: MemoryDraft, request: Request):
    character(request, agent_id)
    if not body.content.strip() or any(len(tag) > 60 for tag in body.tags):
        raise HTTPException(422, "请填写有效的记忆内容")
    provider = request.app.state.embedding_provider
    vector = None
    if provider.dimension > 0:
        try:
            vector = (await anyio.to_thread.run_sync(lambda: provider.embed_documents([body.content])))[0]
        except Exception:
            pass  # 模型暂时不可用时仍保存正文，供关键词召回。
    with SessionLocal() as session:
        digest = fingerprint(body.content)
        if session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id,
                CharacterMemory.fingerprint == digest, CharacterMemory.status.in_(["active", "draft"])).first():
            raise HTTPException(409, "已经有相同内容的记忆")
        row = CharacterMemory(agent_id=agent_id, status="active", source_name="用户编写",
            fingerprint=digest, embedding=vector,
            embedding_model=provider.model_name if vector is not None else None,
            embedding_dim=provider.dimension if vector is not None else None,
            **body.model_dump(mode="json", exclude={"source_quote"}))
        session.add(row)
        session.commit()
        return memory_dict(row)


@router.patch("/{agent_id}/memories/{memory_id}")
async def update(agent_id: str, memory_id: str, body: SaveBody, request: Request):
    character(request, agent_id)
    if body.status not in {"draft", "active", "disabled", "rejected"} or not body.content.strip() or any(len(tag) > 60 for tag in body.tags):
        raise HTTPException(422, "记忆内容或状态无效")
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        if row.perspective.get("story_character_id"):
            if body.status == "active" and not resolve_character_memories(session, [row]):
                raise HTTPException(409, "原作依据已失效，请重新导入核对后再启用")
            if "perspective" in body.model_fields_set and body.perspective.evidence_quote != row.perspective.get("evidence_quote", ""):
                raise HTTPException(422, "原作引用不可改写，请修改角色自己的记忆内容")
        if not row.world_fact_id and body.source_quote != row.source_quote:
            raise HTTPException(422, "来源引用不可改写，请修改记忆正文")
    provider = request.app.state.embedding_provider
    vector = None
    if body.status == "active" and provider.dimension > 0:
        try:
            vector = (await anyio.to_thread.run_sync(lambda: provider.embed_documents([body.content])))[0]
        except Exception:
            pass  # 正式文本仍可关键词检索，之后可统一重建语义索引。
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        for key, value in body.model_dump(mode="json", exclude={"source_quote"}).items():
            if key == "graph" and (row.world_fact_id or "graph" not in body.model_fields_set):
                continue  # 兼容旧客户端，不清空新元数据。
            if key == "perspective" and "perspective" not in body.model_fields_set:
                continue
            if key == "perspective":
                value = {**row.perspective, **value}  # Identity and source hashes cannot be erased by edits.
            setattr(row, key, value)
        row.fingerprint = fingerprint(body.content)
        row.embedding = vector
        row.embedding_model = provider.model_name if vector is not None else None
        row.embedding_dim = provider.dimension if vector is not None else None
        session.commit()
        return memory_dict(row)


@router.delete("/{agent_id}/memories")
async def delete_all_memories(agent_id: str, request: Request):
    character(request, agent_id)
    if request.app.state.character_tasks:
        raise HTTPException(409, "请等待资料提取或记忆构建完成后，再删除全部记忆")
    with SessionLocal() as session:
        deleted = session.query(CharacterMemory).filter(CharacterMemory.agent_id == agent_id).delete(synchronize_session=False)
        session.query(CharacterExtraction).filter(CharacterExtraction.agent_id == agent_id).delete(synchronize_session=False)
        session.commit()
    return {"ok": True, "deleted": deleted}


@router.delete("/{agent_id}/memories/{memory_id}")
def delete(agent_id: str, memory_id: str, request: Request):
    character(request, agent_id)
    with SessionLocal() as session:
        row = session.get(CharacterMemory, memory_id)
        if row is None or row.agent_id != agent_id:
            raise HTTPException(404, "记忆不存在")
        session.delete(row)
        session.commit()
    return {"ok": True}

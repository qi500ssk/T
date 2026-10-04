"""Preview structured stories, import once, and create isolated character memories."""
import anyio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from core.story.document import parse_story, stable_id, markdown, index_events
from core.story.importer import import_story
from core.memory.admission import memory_plan, admission_preview
from core.memory.evidence import digest
from core.rag.ingestion import resolve_stored_file
from infrastructure.config import settings
from infrastructure.database import SessionLocal, Document, WorldFact, CharacterMemory, CharacterStoryBinding

router = APIRouter(prefix="/api/stories", tags=["stories"])


class Input(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    confirmed: bool = False


def checked(text):
    try:
        return parse_story(text)
    except (ValidationError, ValueError) as exc:
        message = exc.errors()[0].get("msg", "格式不正确") if isinstance(exc, ValidationError) else str(exc)
        raise HTTPException(422, "故事文档格式或人物引用无效：" + message) from None


def load_story(document_id):
    with SessionLocal() as session:
        doc = session.get(Document, document_id)
        if not doc: raise HTTPException(404, "文档不存在")
        path = resolve_stored_file(doc.stored_filename, settings)
        if doc.file_type != ".md": raise HTTPException(404, "这不是结构化故事文档")
        try: return parse_story(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError): raise HTTPException(404, "这不是结构化故事文档") from None


def summary(story):
    return {"title":story.title,"basis":story.basis,"source_note":story.source_note,"events":len(story.events),
        "world_entries":len(story.world_entries), "characters":[{**p.model_dump(),"memories":sum(v.character_id==p.id and v.knowledge!="unknown" for e in index_events(story) for v in e.viewpoints),
        "admission": admission_preview(story,p.id)} for p in story.characters]}


@router.post("/preview")
def preview(body: Input):
    story = checked(body.text)
    return {**summary(story), "story": story.model_dump(), "markdown": markdown(story)}


@router.post("/import")
async def import_document(body: Input, request: Request):
    if not body.confirmed: raise HTTPException(422, "请先预览并确认书籍")
    if request.app.state.character_tasks: raise HTTPException(409, "请等待当前资料任务结束")
    story = checked(body.text)
    try:
        doc_id = await anyio.to_thread.run_sync(import_story, story, request.app.state.embedding_provider, settings)
    except Exception:
        raise HTTPException(422, "故事索引未完成，请检查检索模型后重试；未创建角色") from None
    return {"document_id":doc_id, **summary(story)}


@router.get("/{document_id}")
def catalog(document_id: str):
    return summary(load_story(document_id))


@router.post("/{document_id}/characters/{character_id}")
async def create_character(document_id: str, character_id: str, request: Request):
    if request.app.state.character_tasks: raise HTTPException(409, "请等待当前资料任务结束")
    story = load_story(document_id)
    person = next((p for p in story.characters if p.id == character_id), None)
    if not person: raise HTTPException(404, "人物不存在")
    store = request.app.state.runtime_settings_store
    agents = store.snapshot()["agents"]
    agent_id = "story-" + stable_id(document_id, character_id)
    if any(a["id"] == agent_id for a in agents["items"]):
        raise HTTPException(409, "此书籍中的人物已创建")
    profile = {"id":agent_id,"profile_name":person.name,"name":person.name,"role":"故事角色",
        "language":"zh-CN","tone":"自然","verbosity":"适中","humor":"适度","formality":"自然","proactivity":"适度",
        "custom_instructions":f"你正在扮演{person.name}。人物设定：{person.description}\n性格：{person.personality}\n目标：{person.motivation}\n说话方式：{person.speech}\n关系认知：{person.relationships}\n边界：{person.boundaries}\n对话示例：{person.example_dialogue}\n只依据当前角色的专属记忆回忆经历。不知道的事件不要冒充亲历，不使用其他角色的私有记忆，不因用户提到同名人物而改变身份。"}
    names = {p.id:p.name + " [" + p.id + "]" for p in story.characters}
    admitted = memory_plan(story, character_id)
    active = [item for item in admitted if item["status"] == "active"]
    vectors = {}
    embedding_provider = request.app.state.embedding_provider
    if active and embedding_provider.dimension > 0:
        try:
            values = await anyio.to_thread.run_sync(lambda: embedding_provider.embed_documents([item["view"].memory for item in active]))
            if len(values) == len(active): vectors = {item["event"].id: vector for item,vector in zip(active,values)}
        except Exception:
            pass  # Explicitly report lexical fallback; admission does not depend on embedding availability.
    with SessionLocal() as session:
        facts = session.query(WorldFact).filter_by(document_id=document_id, status="active").all()
        # Imported fact IDs encode the event identity; section titles are not identity keys.
        from infrastructure.database import DocumentChunk
        chunks = session.query(DocumentChunk).filter_by(document_id=document_id).order_by(DocumentChunk.chunk_index).all()
        fact_ids = {f.id:f for f in facts}
        created = candidates = 0
        for item in admitted:
            event, view = item["event"], item["view"]
            if item["status"] == "excluded": continue
            event_facts = [fact_ids[stable_id(document_id,event.id,str(c.chunk_index))] for c in chunks if stable_id(document_id,event.id,str(c.chunk_index)) in fact_ids]
            source_chunks = [c for c in chunks if c.id in {f.chunk_id for f in event_facts}]
            if event_facts and len(event_facts) != event_facts[0].graph.get("source_chunk_count",len(event_facts)):
                raise HTTPException(409, "故事来源片段不完整，请重新导入确认后的书籍")
            if not event_facts or any(f.source_hash != digest(next(c.content for c in source_chunks if c.id == f.chunk_id)) for f in event_facts):
                raise HTTPException(409, "故事事件来源已删除或修改，请重新导入确认后的书籍")
            fact = next((f for f in event_facts if view.quote in next(c.content for c in source_chunks if c.id == f.chunk_id)), event_facts[0])
            session.add(CharacterMemory(agent_id=agent_id, world_fact_id=fact.id, content=view.memory, source_quote=view.quote,
                source_name=story.title, source_section=event.stage, document_id=document_id, chunk_id=fact.chunk_id,
                kind="world" if event.id.startswith("lore_") else "experience",
                time_label=event.time,status=item["status"],known_to_character=True,fingerprint=stable_id(agent_id,event.id),
                embedding=vectors.get(event.id), embedding_model=embedding_provider.model_name if event.id in vectors else None,
                embedding_dim=embedding_provider.dimension if event.id in vectors else None,
                graph={"event":event.title,"stage":event.stage,"summary":view.memory[:240],"importance":view.importance,"people":[names[p] for p in view.known_people]},
                perspective={"knowledge":view.knowledge,"story_character_id":character_id,"content":view.memory,"evidence_quote":view.quote,
                    "importance":view.importance,"importance_reason":view.importance_reason,"emotion":view.emotion,
                    "relationship_change":view.relationship_change,"confidence":view.confidence,
                    "event_id":event.id,"parent_event_id":event.parent_event_id,"timeline_order":event.timeline_order,"time_type":event.time_type,
                    "admission_reason":item["reason"], "source_chunks":[{"id":c.id,"hash":digest(c.content)} for c in source_chunks]}))
            if item["status"] == "active": created += 1
            else: candidates += 1
        session.add(CharacterStoryBinding(agent_id=agent_id,document_id=document_id,character_id=character_id,story_title=story.title))
        previous = store.snapshot()["agents"]
        agents["items"].append(profile)
        try:
            session.flush()
            store.update("agents", agents)
            session.commit()
        except Exception:
            session.rollback(); store.update("agents", previous)
            raise
    return {"agent_id":agent_id,"name":person.name,"memories":created,"candidates":candidates,
            "semantic_indexed":len(vectors),"lexical_only":created-len(vectors)}

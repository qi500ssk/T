"""Worldbook job control and explicit export/import actions."""
import asyncio
from types import SimpleNamespace
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import anyio
from core.story.build import run_build, output_path, assembled, default_output_dir
from core.story.importer import import_story
from core.chat.gateway import build_provider
from core.capabilities.web_search import WebSearchService
from core.files.workspaces import resolve_workspace, workspace_root
from infrastructure.config import settings
from infrastructure.database import SessionLocal, StoryBuild, Message, Document, Conversation
from core.story.proposal import parse_proposal

router = APIRouter(prefix="/api/story-builds", tags=["story-builds"])

class BuildInput(BaseModel):
    brief: str = Field(min_length=20, max_length=16000)
    output_dir: str = Field(default="", max_length=1200)
    chapter_count: int = Field(default=12, ge=2, le=30)
    min_chapter_chars: int = Field(default=800, ge=400, le=2500)
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    research_query: str = Field(default="", max_length=200)

def get_job(session, job_id):
    row = session.get(StoryBuild, job_id)
    if not row: raise HTTPException(404, "生成任务不存在")
    return row

def snapshot(row, request):
    running = "story:"+row.id in request.app.state.character_tasks
    status = row.status
    if status in {"planning","writing","pending"} and not running: status = "paused"
    return {"id":row.id,"title":row.title,"status":status,"running":running,"completed":len(row.chapters),
        "total":row.request["chapter_count"],"output_path":str(output_path(row)),"plan":row.plan,
        "report":row.report,"error":row.error,"document_id":row.document_id,"request_message_id":row.request.get("message_id"),
        "synopsis": next((e['text'][:180] for c in row.chapters for e in c['events']), ''),
        "files":[p.name for p in output_path(row).iterdir() if p.is_file() and p.suffix in {".md",".json",".txt",".epub"}]}

def launch(job_id, request):
    tasks = request.app.state.character_tasks
    key = "story:"+job_id
    if key in tasks: raise HTTPException(409, "任务已在运行")
    if any(k.startswith("story:") for k in tasks): raise HTTPException(409, "请先停止或完成当前书籍任务")
    if settings.llm_provider == "unconfigured": raise HTTPException(409, "请先配置聊天模型")
    config = SimpleNamespace(**settings.model_dump())
    # Chapter outputs are bounded independently of the whole book.
    config.llm_max_output_tokens = max(getattr(config, "llm_max_output_tokens", 4096), 6000)
    provider = build_provider(config)
    provider.structured_output = True
    task = asyncio.create_task(run_build(job_id, provider, WebSearchService(request.app.state.runtime_settings_store)))
    tasks[key] = task
    task.add_done_callback(lambda _: tasks.pop(key, None))

@router.get("")
def listing(request: Request):
    with SessionLocal() as session:
        return {"default_output_dir":str(workspace_root()),"jobs":[snapshot(row, request) for row in session.query(StoryBuild).order_by(StoryBuild.created_at.desc()).limit(50)]}


def conversation_proposal(session, conversation_id, request):
    conversation = session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "对话不存在")
    profile = next((p for p in request.app.state.runtime_settings_store.snapshot()["agents"]["items"] if p["id"] == conversation.agent_id), None)
    from core.story.assistant import is_story_assistant
    if not profile or (not is_story_assistant(conversation.agent_id) and "story-build" not in profile.get("custom_instructions", "")):
        raise HTTPException(404, "此对话不是故事创作对话")
    message = session.query(Message).filter_by(conversation_id=conversation_id, role="assistant", status="completed").order_by(Message.created_at.desc()).first()
    proposal = parse_proposal(message.content) if message else None
    return message, proposal


@router.get("/conversation/{conversation_id}")
def chat_status(conversation_id: str, request: Request):
    with SessionLocal() as session:
        message, proposal = conversation_proposal(session, conversation_id, request)
        rows = session.query(StoryBuild).filter(StoryBuild.request["conversation_id"].as_string() == conversation_id).order_by(StoryBuild.created_at.desc()).all()
        return {"proposal": proposal.model_dump() if proposal else None, "message_id": message.id if proposal else None,
                "jobs": [snapshot(row, request) for row in rows]}


class StartFromChat(BaseModel):
    message_id: str = Field(min_length=1, max_length=32)


@router.post("/conversation/{conversation_id}/start")
async def start_from_chat(conversation_id: str, body: StartFromChat, request: Request):
    with SessionLocal() as session:
        message, proposal = conversation_proposal(session, conversation_id, request)
        if not proposal or message.id != body.message_id:
            raise HTTPException(409, "创作需求已变化，请刷新后确认最新方案")
        existing = session.query(StoryBuild).filter(StoryBuild.request["message_id"].as_string() == message.id).first()
        if existing:
            return {"id": existing.id}
    result = await create(BuildInput(**proposal.model_dump()), request)
    with SessionLocal() as session:
        row = get_job(session, result["id"])
        row.request = {**row.request, "conversation_id": conversation_id, "message_id": body.message_id}
        session.commit()
    return result

@router.get("/brief/{conversation_id}")
def conversation_brief(conversation_id: str):
    with SessionLocal() as session:
        rows = session.query(Message).filter_by(conversation_id=conversation_id).order_by(Message.created_at.desc()).limit(40).all()
        text = "\n\n".join(f"{m.role}: {m.content}" for m in reversed(rows))
        return {"brief":text[-16000:],"truncated":len(text)>16000 or len(rows)==40}

@router.post("")
async def create(body: BuildInput, request: Request):
    try: path = resolve_workspace(body.output_dir) if body.output_dir else default_output_dir()
    except ValueError as exc: raise HTTPException(422, str(exc)) from None
    if settings.llm_provider == "unconfigured": raise HTTPException(409, "请先配置聊天模型")
    if any(k.startswith("story:") for k in request.app.state.character_tasks): raise HTTPException(409, "已有书籍任务正在运行")
    with SessionLocal() as session:
        if body.document_ids and session.query(Document).filter(Document.id.in_(set(body.document_ids)),Document.status=="indexed").count()!=len(set(body.document_ids)):
            raise HTTPException(422, "所选资料不存在或尚未索引")
        row = StoryBuild(request=body.model_dump(), output_dir=str(path))
        session.add(row); session.flush()
        try: output_path(row)
        except (OSError,ValueError):
            session.rollback()
            raise HTTPException(422, "无法在所选位置创建生成目录，请选择可写文件夹") from None
        session.commit()
        job_id = row.id
    launch(job_id, request)
    return {"id":job_id}

@router.post("/{job_id}/continue")
async def resume(job_id: str, request: Request):
    with SessionLocal() as session:
        row = get_job(session, job_id)
        if row.status in {"review","imported"}: raise HTTPException(409, "正文已生成，请检查或导入")
    launch(job_id, request)
    return {"ok":True}

@router.post("/{job_id}/stop")
async def stop(job_id: str, request: Request):
    task = request.app.state.character_tasks.get("story:"+job_id)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    return {"ok":True}

@router.get("/{job_id}/files/{name}")
def download(job_id: str, name: str):
    with SessionLocal() as session: row = get_job(session, job_id)
    folder = output_path(row)
    if "/" in name or "\\" in name or name not in {p.name for p in folder.iterdir() if p.suffix in {".md",".json",".txt",".epub"}}:
        raise HTTPException(404, "文件不存在")
    path = folder / name
    if path.is_symlink() or path.resolve().parent != folder: raise HTTPException(404, "文件不可用")
    return FileResponse(path, filename=name)


@router.get("/{job_id}/read")
def read_generated_book(job_id: str, page: int = Query(default=0, ge=0)):
    from core.story.reader import story_book
    with SessionLocal() as session:
        row = get_job(session, job_id)
        if row.status not in {'review', 'imported'}:
            raise HTTPException(409, '书籍尚未生成完成')
        book = story_book(assembled(row))
    pages = book.pop('sections')
    if page >= len(pages):
        raise HTTPException(404, '页码不存在')
    return {**book, 'id': job_id, 'page': page, 'total': len(pages), 'content': pages[page],
        'chapters': [{'title': s['title'], 'characters': len(s['text'])} for s in pages]}

@router.post("/{job_id}/import")
async def confirm_import(job_id: str, request: Request):
    with SessionLocal() as session:
        row = get_job(session, job_id)
        if row.status == "imported": return {"document_id":row.document_id}
        if row.status != "review": raise HTTPException(409, "请先完成正文生成和检查")
        story = assembled(row)
    if request.app.state.character_tasks: raise HTTPException(409, "请等待当前生成或资料任务结束")
    try: doc_id = await anyio.to_thread.run_sync(import_story, story, request.app.state.embedding_provider, settings)
    except Exception: raise HTTPException(422, "索引失败，已生成的文档仍保留，可重试") from None
    with SessionLocal() as session:
        row = get_job(session, job_id); row.document_id=doc_id;row.status="imported";session.commit()
    return {"document_id":doc_id}

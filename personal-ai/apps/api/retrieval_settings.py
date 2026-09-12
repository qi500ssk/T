"""检索模型设置、显式下载、原子替换索引；密钥仅存在本地设置文件。"""
import asyncio
from contextlib import suppress
from types import SimpleNamespace
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.rag.embedding import LOCAL_MODELS, DEFAULT_LOCAL_MODEL, build_embedding_provider
from core.rag.local_models import cached_model_directory, discover_local_models, inspect_local_model
from infrastructure.paths import data_path
from core.settings.runtime import EMBEDDING_FIELDS
from infrastructure.config import settings
from infrastructure.database import AgentRun, Document, DocumentChunk, Memory, CharacterMemory, SessionLocal

router = APIRouter(prefix="/api/settings/retrieval", tags=["retrieval"])


class RetrievalMaintenanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        state = scope["app"].state
        exempt = scope["path"].startswith(("/api/settings/retrieval", "/api/auth/"))
        if not exempt and getattr(state, "retrieval_maintenance", False):
            from starlette.responses import JSONResponse
            return await JSONResponse({"detail": "检索模型正在更新，请稍后重试"}, 503)(scope, receive, send)
        if not exempt:
            state.retrieval_requests = getattr(state, "retrieval_requests", 0) + 1
        try:
            await self.app(scope, receive, send)
        finally:
            if not exempt:
                state.retrieval_requests -= 1


class RetrievalBody(BaseModel):
    provider: str = "fastembed"
    model: str = Field(default=DEFAULT_LOCAL_MODEL, max_length=200)
    base_url: str = Field(default="", max_length=1000)
    api_key: str | None = Field(default=None, max_length=4096)
    dimension: int = Field(default=1536, ge=1, le=4096)
    request_dimensions: bool = False
    download: bool = False
    model_path: str = Field(default="", max_length=1200)
    query_instruction: str = Field(default="", max_length=300)


def values_for(body, previous):
    if body.provider not in {"keyword", "fastembed", "local", "openai-compatible"}:
        raise HTTPException(422, "请选择关键词、本地模型或在线 Embedding")
    values = dict(previous)
    values.update(embedding_provider=body.provider, embedding_model=body.model.strip(),
                  embedding_model_path="", embedding_query_instruction="",
                  embedding_request_dimensions=body.request_dimensions)
    if body.provider == "fastembed":
        if body.model not in LOCAL_MODELS:
            raise HTTPException(422, "本地模型不在支持列表中")
        values["embedding_dim"] = LOCAL_MODELS[body.model]["dimension"]
    elif body.provider == "local":
        try:
            local = inspect_local_model(body.model_path)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, str(error) if isinstance(error, ValueError) else "模型目录无法读取或配置无效") from None
        if not local["runtime_ready"]:
            raise HTTPException(422, "当前安装缺少已有模型运行组件，请安装 legacy-embedding 可选依赖后重启；不会自动下载模型或依赖")
        values.update(embedding_model_path=local["path"], embedding_dim=local["dimension"],
                      embedding_model=local["name"], embedding_query_instruction=body.query_instruction)
    elif body.provider == "keyword":
        values["embedding_dim"] = 0
    else:
        try:
            parsed = urlsplit(body.base_url.strip())
            parsed.port  # 同时校验非法端口和不完整 IPv6 地址。
        except ValueError:
            raise HTTPException(422, "请输入有效的 HTTP(S) 服务地址") from None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise HTTPException(422, "请输入有效的 HTTP(S) 服务地址，不要在地址中填写密钥")
        key = body.api_key
        if key is None:
            if body.base_url.rstrip("/") != str(previous.get("embedding_base_url", "")).rstrip("/"):
                raise HTTPException(422, "更换服务地址时请重新输入 API Key")
            key = previous.get("embedding_api_key", "")
        if not key or not body.model.strip():
            raise HTTPException(422, "在线模型需要模型名和 API Key")
        values.update(embedding_dim=body.dimension, embedding_base_url=body.base_url.strip().rstrip("/"), embedding_api_key=key)
    return values


def public_status(request):
    state = request.app.state
    values = state.runtime_settings_store.snapshot()["embedding"]
    provider = state.embedding_provider
    return {
        "provider": values["embedding_provider"], "model": values["embedding_model"],
        "dimension": values["embedding_dim"], "base_url": values["embedding_base_url"],
        "has_api_key": bool(values["embedding_api_key"]),
        "request_dimensions": values["embedding_request_dimensions"],
        "active_model": provider.model_name, "semantic_ready": provider.dimension > 0,
        "retrieval_mode": "hybrid" if provider.dimension > 0 else "keyword",
        "cache_dir": data_path("embedding-models"), "model_path": values["embedding_model_path"],
        "query_instruction": values["embedding_query_instruction"],
        "notice": getattr(provider, "reason", ""),
        "models": [{"id": key, **value, "cached_path": cached_model_directory(key)} for key, value in LOCAL_MODELS.items()],
        "job": getattr(state, "retrieval_job", {"status": "idle", "processed": 0, "total": 0}),
    }


@router.get("")
def status(request: Request):
    return public_status(request)


@router.get("/local-models")
def local_models():
    return {"models": discover_local_models()}


class LocalModelBody(BaseModel):
    path: str = Field(min_length=1, max_length=1200)


@router.post("/inspect-local")
def inspect_local(body: LocalModelBody):
    try:
        return inspect_local_model(body.path)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, str(error) if isinstance(error, ValueError) else "模型目录无法读取或配置无效") from None


def rebuild(provider, values, store, progress):
    """先准备全部向量，成功后一次事务替换；保留 chunk ID 及角色来源引用。"""
    with SessionLocal() as session:
        documents = session.query(Document).filter(Document.status == "indexed").all()
        doc_ids = [row.id for row in documents]
        chunks = session.query(DocumentChunk).filter(DocumentChunk.document_id.in_(doc_ids)).all()
        memories = session.query(Memory).filter(Memory.status == "active").all()
        characters = session.query(CharacterMemory).filter(CharacterMemory.status == "active").all()
        rows = [(DocumentChunk, row.id, row.content) for row in chunks]
        rows += [(Memory, row.id, row.content) for row in memories]
        rows += [(CharacterMemory, row.id, row.content) for row in characters]
    progress.update(status="indexing", total=len(rows), processed=0)
    vectors = []
    for start in range(0, len(rows), 16):
        batch = provider.embed_documents([row[2] for row in rows[start:start + 16]])
        if len(batch) != len(rows[start:start + 16]):
            raise ValueError("模型返回数量不匹配")
        vectors.extend(batch)
        progress["processed"] = len(vectors)
    previous = store.snapshot()["embedding"]
    saved = False
    try:
        with SessionLocal() as session:
            for (model, identifier, content), vector in zip(rows, vectors, strict=True):
                row = session.get(model, identifier)
                if row is None or row.content != content:
                    raise RuntimeError("重建期间资料发生变化")
                row.embedding = vector
                if model is not DocumentChunk:
                    row.embedding_model, row.embedding_dim = provider.model_name, provider.dimension
            for identifier in doc_ids:
                row = session.get(Document, identifier)
                if row is None or row.status != "indexed":
                    raise RuntimeError("重建期间资料发生变化")
                row.embedding_model, row.embedding_dim = provider.model_name, provider.dimension
            session.flush()
            store.update("embedding", values)
            saved = True
            session.commit()
    except Exception:
        if saved:
            store.update("embedding", previous)
        raise


async def _change(request, body, values):
    state = request.app.state
    candidate = None
    try:
        candidate = await anyio.to_thread.run_sync(lambda: build_embedding_provider(SimpleNamespace(**values), download=body.download, strict=True))
        # 即使资料库为空，也验证实际推理，而非只验证连接参数。
        await anyio.to_thread.run_sync(lambda: candidate.embed_query("模型连接测试"))
        await anyio.to_thread.run_sync(lambda: rebuild(candidate, values, state.runtime_settings_store, state.retrieval_job))
        previous = state.embedding_provider
        state.embedding_provider = candidate
        for name in EMBEDDING_FIELDS:
            setattr(settings, name, values[name])
        candidate = None
        with suppress(Exception):
            previous.close()
        state.retrieval_job["status"] = "completed"
    except asyncio.CancelledError:
        state.retrieval_job.update(status="failed", error="更新已中断，可重新操作；原文保留")
        raise
    except Exception:
        detail = "已有模型加载失败，请检查目录完整性及运行组件；不会补下载文件。" if body.provider == "local" else "模型下载、测试或重建失败。请检查网络、API Key 和模型维度。"
        state.retrieval_job.update(status="failed", error=detail + "旧配置与原文保留。")
    finally:
        if candidate is not None:
            with suppress(Exception):
                candidate.close()
        state.retrieval_maintenance = False
        if settings.activity_enabled:
            from core.automation.activity import activity_worker
            from core.settings.runtime import resolve_agent_profile
            state.activity_stop_event = asyncio.Event()
            state.activity_task = asyncio.create_task(activity_worker(
                state.activity_stop_event, state.provider, state.embedding_provider, state.skills,
                state.agent_profile, state.mcp_manager,
                lambda agent_id: resolve_agent_profile(state.runtime_settings_store.snapshot(), agent_id),
            ))


@router.post("", status_code=202)
async def change(body: RetrievalBody, request: Request):
    state = request.app.state
    async with state.runtime_settings_lock:
        if state.retrieval_maintenance or state.retrieval_requests or getattr(state, "character_tasks", {}):
            raise HTTPException(409, "请等待聊天、资料处理或角色提取结束后再切换")
        with SessionLocal() as session:
            if session.query(AgentRun).filter(AgentRun.status == "running").first():
                raise HTTPException(409, "存在运行中的任务，请稍后切换")
        values = values_for(body, state.runtime_settings_store.snapshot()["embedding"])
        state.retrieval_maintenance = True
        if state.activity_task is not None:
            state.activity_stop_event.set()
            state.activity_task.cancel()
            with suppress(asyncio.CancelledError):
                await state.activity_task
            state.activity_task = None
        state.retrieval_job = {"status": "preparing", "processed": 0, "total": 0, "error": None}
        state.retrieval_task = asyncio.create_task(_change(request, body, values))
        return public_status(request)

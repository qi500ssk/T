"""Skill Manager：动态扫描、状态持久化与管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from core.capabilities.registry import build_capability_registry
from core.capabilities.skill_packages import (
    MAX_FILE_BYTES,
    SkillConflictError,
    SkillPackageError,
    create_skill,
    install_skill_folder,
    remove_local_skill,
)
from core.capabilities.skill_registry import build_default_skill_registry
from core.capabilities.skills import SkillRecord
from infrastructure.database import AssistantSkill, SessionLocal


router = APIRouter(prefix="/api/skills", tags=["skills"])
DEFAULT_ASSISTANT_ID = "default"


class SkillToggleRequest(BaseModel):
    enabled: bool


class SkillCreateRequest(BaseModel):
    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    instructions: str = Field(min_length=1, max_length=20_000)
    required_tools: list[str] = Field(default_factory=list, max_length=20)


def _state_map(assistant_id: str = DEFAULT_ASSISTANT_ID) -> dict[str, bool]:
    with SessionLocal() as session:
        rows = (
            session.query(AssistantSkill)
            .filter(AssistantSkill.assistant_id == assistant_id)
            .all()
        )
        return {row.skill_id: row.enabled for row in rows}


def _enabled(record: SkillRecord, states: dict[str, bool]) -> bool:
    requested = states.get(record.id, record.default_enabled)
    return requested and record.available and record.error is None


def _status(record: SkillRecord, enabled: bool) -> str:
    if record.error and record.error.startswith("格式错误："):
        return "invalid"
    if not record.available:
        return "missing_dependencies"
    return "enabled" if enabled else "disabled"


def serialize_skill(record: SkillRecord, states: dict[str, bool]) -> dict:
    enabled = _enabled(record, states)
    return {
        "id": record.id,
        "name": record.name,
        "description": record.description,
        "source": record.source,
        "required_tools": list(record.required_tools),
        "enabled": enabled,
        "available": record.available and record.error is None,
        "status": _status(record, enabled),
        "error": record.error,
        "instructions": record.instructions,
        "deletable": record.source in {"local", "online"},
    }


def refresh_skill_runtime(app) -> list[SkillRecord]:
    """重新扫描并原地更新运行时列表，使后台 Worker 也看到新快照。"""
    registry = getattr(app.state, "skill_registry", None)
    if registry is None:
        registry = build_default_skill_registry()
        app.state.skill_registry = registry
    snapshot = registry.snapshot()
    records = list(snapshot.records)
    states = _state_map()
    active = [record.as_skill() for record in records if _enabled(record, states)]
    if hasattr(app.state, "skills"):
        app.state.skills[:] = active
    else:
        app.state.skills = active
    app.state.skill_catalog = records
    app.state.skill_catalog_version = snapshot.version
    app.state.skill_catalog_complete = snapshot.complete
    app.state.capability_registry = build_capability_registry(
        app.state.skills, app.state.mcp_clients
    )
    return records


def _catalog(request: Request) -> list[SkillRecord]:
    records = getattr(request.app.state, "skill_catalog", None)
    return records if records is not None else refresh_skill_runtime(request.app)


@router.get("")
def list_skills(request: Request):
    states = _state_map()
    return [serialize_skill(record, states) for record in _catalog(request)]


@router.get("/catalog")
def skill_catalog_status(request: Request):
    records = _catalog(request)
    return {
        "version": request.app.state.skill_catalog_version,
        "complete": request.app.state.skill_catalog_complete,
        "skill_count": len(records),
    }


@router.post("/refresh")
def refresh_skills(request: Request):
    records = refresh_skill_runtime(request.app)
    states = _state_map()
    return [serialize_skill(record, states) for record in records]


def _package_error(exc: SkillPackageError) -> HTTPException:
    return HTTPException(409 if isinstance(exc, SkillConflictError) else 422, str(exc))


@router.post("/import-folder")
async def import_skill_folder(
    request: Request,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
):
    if len(files) != len(paths):
        raise HTTPException(422, "文件与相对路径数量不一致")
    entries: list[tuple[str, bytes]] = []
    for path, upload in zip(paths, files, strict=True):
        content = await upload.read(MAX_FILE_BYTES + 1)
        entries.append((path, content))
    try:
        installed = install_skill_folder(entries)
    except SkillPackageError as exc:
        raise _package_error(exc) from exc
    records = refresh_skill_runtime(request.app)
    latest = next(item for item in records if item.id == installed.id)
    return serialize_skill(latest, _state_map())


@router.post("")
def add_skill(body: SkillCreateRequest, request: Request):
    try:
        created = create_skill(
            body.id,
            body.name,
            body.description,
            body.instructions,
            body.required_tools,
        )
    except SkillPackageError as exc:
        raise _package_error(exc) from exc
    records = refresh_skill_runtime(request.app)
    latest = next(item for item in records if item.id == created.id)
    return serialize_skill(latest, _state_map())


@router.patch("/{skill_id}")
def toggle_skill(skill_id: str, body: SkillToggleRequest, request: Request):
    record = next((item for item in _catalog(request) if item.id == skill_id), None)
    if record is None:
        raise HTTPException(404, "skill not found")
    if body.enabled and (not record.available or record.error is not None):
        raise HTTPException(409, record.error or "Skill 当前不可用")

    with SessionLocal() as session:
        state = session.get(AssistantSkill, (DEFAULT_ASSISTANT_ID, skill_id))
        if state is None:
            state = AssistantSkill(
                assistant_id=DEFAULT_ASSISTANT_ID,
                skill_id=skill_id,
                enabled=body.enabled,
            )
            session.add(state)
        else:
            state.enabled = body.enabled
        session.commit()

    refresh_skill_runtime(request.app)
    states = _state_map()
    latest = next(item for item in request.app.state.skill_catalog if item.id == skill_id)
    return serialize_skill(latest, states)


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, request: Request):
    record = next((item for item in _catalog(request) if item.id == skill_id), None)
    if record is None:
        raise HTTPException(404, "skill not found")
    try:
        destination = remove_local_skill(record)
    except SkillPackageError as exc:
        raise _package_error(exc) from exc
    with SessionLocal() as session:
        state = session.get(AssistantSkill, (DEFAULT_ASSISTANT_ID, skill_id))
        if state is not None:
            session.delete(state)
            session.commit()
    refresh_skill_runtime(request.app)
    return {"ok": True, "recoverable": True, "trash_name": destination.name}

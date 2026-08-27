"""项目 API：用项目组织任务，并保存每个项目的本地工作目录。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.chat.images import resolve_image
from infrastructure.database import (
    Activity,
    AgentRun,
    ChatImage,
    Conversation,
    Memory,
    Message,
    Plan,
    PlanStep,
    Project,
    ProjectAgentAccess,
    SessionLocal,
    ToolRun,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_dir: str = Field(min_length=1, max_length=1200)
    agent_id: str | None = Field(default=None, max_length=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    workspace_dir: str | None = Field(default=None, max_length=1200)


def _normalize_workspace(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    path = Path(value.strip()).expanduser()
    if not path.is_absolute():
        raise HTTPException(422, "workspace_dir 必须是绝对路径")
    if not path.exists() or not path.is_dir():
        raise HTTPException(422, "workspace_dir 不存在或不是文件夹")
    return str(path.resolve())


def _project_dict(project: Project, session) -> dict:
    agent_ids = [
        row.agent_id
        for row in session.query(ProjectAgentAccess.agent_id)
        .filter(ProjectAgentAccess.project_id == project.id)
        .order_by(ProjectAgentAccess.created_at.asc())
    ]
    return {
        "id": project.id,
        "name": project.name,
        "workspace_dir": project.workspace_dir,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "agent_ids": agent_ids,
    }


def _agent_id(request: Request, requested: str | None) -> str:
    agents = request.app.state.runtime_settings_store.snapshot()["agents"]
    agent_id = requested or agents["active_agent_id"]
    if not any(item["id"] == agent_id for item in agents["items"]):
        raise HTTPException(404, "角色不存在")
    return agent_id


def _delete_conversation_records(session, conversation_ids: list[str]) -> list[str]:
    if not conversation_ids:
        return []
    if (
        session.query(AgentRun)
        .filter(
            AgentRun.conversation_id.in_(conversation_ids),
            AgentRun.status == "running",
        )
        .first()
    ):
        raise HTTPException(409, "文件夹中有正在运行的对话，暂时不能移除")
    run_ids = [
        row.id
        for row in session.query(AgentRun.id).filter(
            AgentRun.conversation_id.in_(conversation_ids)
        )
    ]
    plan_ids = [
        row.id
        for row in session.query(Plan.id).filter(Plan.conversation_id.in_(conversation_ids))
    ]
    message_ids = [
        row.id
        for row in session.query(Message.id).filter(
            Message.conversation_id.in_(conversation_ids)
        )
    ]
    stored_images = (
        [
            row.stored_filename
            for row in session.query(ChatImage.stored_filename).filter(
                ChatImage.message_id.in_(message_ids)
            )
        ]
        if message_ids
        else []
    )
    if message_ids:
        session.query(ChatImage).filter(ChatImage.message_id.in_(message_ids)).delete(
            synchronize_session=False
        )
    if run_ids:
        session.query(ToolRun).filter(ToolRun.run_id.in_(run_ids)).delete(
            synchronize_session=False
        )
    if plan_ids:
        session.query(PlanStep).filter(PlanStep.plan_id.in_(plan_ids)).delete(
            synchronize_session=False
        )
        session.query(Plan).filter(Plan.id.in_(plan_ids)).delete(
            synchronize_session=False
        )
    if run_ids:
        session.query(AgentRun).filter(AgentRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )
    session.query(Activity).filter(Activity.conversation_id.in_(conversation_ids)).delete(
        synchronize_session=False
    )
    if message_ids:
        session.query(Message).filter(Message.id.in_(message_ids)).delete(
            synchronize_session=False
        )
    session.query(Memory).filter(
        (Memory.scope_type == "conversation")
        & (Memory.scope_key.in_(conversation_ids))
    ).delete(synchronize_session=False)
    session.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(
        synchronize_session=False
    )
    return stored_images


def _unlink_images(stored_images: list[str]) -> None:
    for stored_filename in stored_images:
        try:
            resolve_image(stored_filename).unlink(missing_ok=True)
        except FileNotFoundError:
            pass


@router.get("")
def list_projects():
    with SessionLocal() as session:
        rows = session.query(Project).order_by(Project.updated_at.desc()).all()
        return [_project_dict(row, session) for row in rows]


@router.post("")
def create_project(body: ProjectCreate, request: Request):
    agent_id = _agent_id(request, body.agent_id)
    with SessionLocal() as session:
        project = Project(
            name=body.name.strip(),
            workspace_dir=_normalize_workspace(body.workspace_dir),
        )
        session.add(project)
        session.flush()
        session.add(ProjectAgentAccess(project_id=project.id, agent_id=agent_id))
        session.commit()
        return _project_dict(project, session)


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectUpdate):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        if body.name is not None:
            project.name = body.name.strip()
        if "workspace_dir" in body.model_fields_set:
            project.workspace_dir = _normalize_workspace(body.workspace_dir)
        session.commit()
        return _project_dict(project, session)


@router.post("/{project_id}/agents/{agent_id}")
def grant_project_access(project_id: str, agent_id: str, request: Request):
    _agent_id(request, agent_id)
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        access = session.get(
            ProjectAgentAccess,
            {"project_id": project_id, "agent_id": agent_id},
        )
        if access is None:
            session.add(ProjectAgentAccess(project_id=project_id, agent_id=agent_id))
            session.commit()
        return _project_dict(project, session)


@router.delete("/{project_id}/agents/{agent_id}")
def revoke_project_access(
    project_id: str,
    agent_id: str,
    delete_conversations: bool = Query(default=False),
):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        access = session.get(
            ProjectAgentAccess,
            {"project_id": project_id, "agent_id": agent_id},
        )
        if access is None:
            raise HTTPException(404, "此角色未被授权访问该项目")
        conversation_ids = [
            row.id
            for row in session.query(Conversation.id).filter(
                Conversation.project_id == project_id,
                Conversation.agent_id == agent_id,
            )
        ]
        if conversation_ids and not delete_conversations:
            raise HTTPException(409, "请先删除此角色在项目中的对话")
        stored_images = _delete_conversation_records(session, conversation_ids)
        session.delete(access)
        session.flush()
        project_deleted = not session.query(ProjectAgentAccess).filter(
            ProjectAgentAccess.project_id == project_id
        ).first()
        if project_deleted:
            session.query(Memory).filter(
                Memory.scope_type == "project",
                Memory.scope_key == project_id,
            ).delete(synchronize_session=False)
            session.delete(project)
        session.commit()
    _unlink_images(stored_images)
    return {"ok": True, "project_deleted": project_deleted}


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    delete_conversations: bool = Query(
        default=False,
        description="同时永久删除文件夹下的全部对话及关联记录",
    ),
):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        conversation_ids = [
            row.id
            for row in session.query(Conversation.id).filter(Conversation.project_id == project_id)
        ]
        stored_images: list[str] = []
        if conversation_ids:
            if not delete_conversations:
                raise HTTPException(409, "请先删除或移走项目中的任务")
            stored_images = _delete_conversation_records(session, conversation_ids)
        session.query(Memory).filter(
            Memory.scope_type == "project",
            Memory.scope_key == project_id,
        ).delete(synchronize_session=False)
        session.delete(project)
        session.commit()
        _unlink_images(stored_images)
        return {"ok": True}

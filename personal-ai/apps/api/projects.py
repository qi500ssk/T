"""项目 API：用项目组织任务，并保存每个项目的本地工作目录。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
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
    SessionLocal,
    ToolRun,
)


router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_dir: str = Field(min_length=1, max_length=1200)


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


def _project_dict(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "workspace_dir": project.workspace_dir,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }


@router.get("")
def list_projects():
    with SessionLocal() as session:
        rows = session.query(Project).order_by(Project.updated_at.desc()).all()
        return [_project_dict(row) for row in rows]


@router.post("")
def create_project(body: ProjectCreate):
    with SessionLocal() as session:
        project = Project(
            name=body.name.strip(),
            workspace_dir=_normalize_workspace(body.workspace_dir),
        )
        session.add(project)
        session.commit()
        return _project_dict(project)


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
        return _project_dict(project)


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
            if (
                session.query(AgentRun)
                .filter(
                    AgentRun.conversation_id.in_(conversation_ids),
                    AgentRun.status == "running",
                )
                .first()
            ):
                raise HTTPException(409, "文件夹中有正在运行的对话，暂时不能删除")

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
            if message_ids:
                stored_images = [
                    row.stored_filename
                    for row in session.query(ChatImage.stored_filename).filter(
                        ChatImage.message_id.in_(message_ids)
                    )
                ]
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
                (
                    (Memory.scope_type == "project")
                    & (Memory.scope_key == project_id)
                )
                | (
                    (Memory.scope_type == "conversation")
                    & (Memory.scope_key.in_(conversation_ids))
                )
            ).delete(synchronize_session=False)
            session.query(Conversation).filter(Conversation.id.in_(conversation_ids)).delete(
                synchronize_session=False
            )
        session.delete(project)
        session.commit()
        for stored_filename in stored_images:
            try:
                resolve_image(stored_filename).unlink(missing_ok=True)
            except FileNotFoundError:
                pass
        return {"ok": True}

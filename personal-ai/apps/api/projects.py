"""项目 API：用项目组织任务，并保存每个项目的本地工作目录。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from infrastructure.database import Conversation, Project, SessionLocal


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
def delete_project(project_id: str):
    with SessionLocal() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "project not found")
        if session.query(Conversation).filter(Conversation.project_id == project_id).first():
            raise HTTPException(409, "请先删除或移走项目中的任务")
        session.delete(project)
        session.commit()
        return {"ok": True}

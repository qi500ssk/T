"""生成文件列表与安全下载 API。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.files.artifacts import ArtifactError, list_artifacts, resolve_artifact


router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.get("")
def get_artifacts():
    return [item.public() for item in list_artifacts()]


@router.get("/{artifact_id}")
def download_artifact(artifact_id: str):
    try:
        record = resolve_artifact(artifact_id)
    except ArtifactError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(
        record.path,
        filename=record.filename,
        media_type=MEDIA_TYPES[record.path.suffix.lower()],
    )

"""本地聊天图片上传、预览和暂存删除 API。"""

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.chat.images import (
    InvalidChatImageError,
    inspect_image,
    resolve_image,
    save_image,
)
from infrastructure.config import settings
from infrastructure.database import ChatImage, SessionLocal


router = APIRouter(prefix="/api/chat/images")


def image_dict(image: ChatImage) -> dict:
    return {
        "id": image.id,
        "original_filename": image.original_filename,
        "mime_type": image.mime_type,
        "size_bytes": image.size_bytes,
        "width": image.width,
        "height": image.height,
        "created_at": image.created_at.isoformat(),
    }


@router.post("", status_code=201)
async def upload_chat_image(file: UploadFile = File(...)):
    data = await file.read(settings.chat_image_max_bytes + 1)
    if len(data) > settings.chat_image_max_bytes:
        raise HTTPException(413, f"图片大小超过限制：{settings.chat_image_max_bytes} 字节")
    if not data:
        raise HTTPException(415, "图片内容为空")
    original_filename = Path(file.filename or "image").name
    try:
        mime_type, extension, width, height = inspect_image(data, original_filename)
    except InvalidChatImageError as exc:
        raise HTTPException(415, str(exc)) from exc
    stored_filename = save_image(data, extension)
    image = ChatImage(
        user_id="default",
        original_filename=original_filename,
        stored_filename=stored_filename,
        mime_type=mime_type,
        size_bytes=len(data),
        width=width,
        height=height,
    )
    try:
        with SessionLocal() as session:
            session.add(image)
            session.commit()
    except Exception:
        resolve_image(stored_filename).unlink(missing_ok=True)
        raise
    return image_dict(image)


@router.get("/{image_id}/content")
def get_chat_image_content(image_id: str):
    with SessionLocal() as session:
        image = session.get(ChatImage, image_id)
        if image is None:
            raise HTTPException(404, "image not found")
        try:
            path = resolve_image(image.stored_filename)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            path,
            media_type=image.mime_type,
            filename=image.original_filename,
            content_disposition_type="inline",
        )


@router.delete("/{image_id}")
def delete_staged_chat_image(image_id: str):
    with SessionLocal() as session:
        image = session.get(ChatImage, image_id)
        if image is None:
            raise HTTPException(404, "image not found")
        if image.message_id is not None:
            raise HTTPException(409, "已发送的图片不能单独删除")
        stored_filename = image.stored_filename
        session.delete(image)
        session.commit()
    try:
        resolve_image(stored_filename).unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    return {"ok": True}

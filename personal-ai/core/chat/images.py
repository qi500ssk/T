"""聊天图片的格式校验、安全落盘与多模态消息编码。"""

from __future__ import annotations

import base64
from pathlib import Path
import struct
import uuid

from infrastructure.config import settings


class InvalidChatImageError(ValueError):
    pass


_FORMATS = {
    "jpeg": ("image/jpeg", ".jpg", {".jpg", ".jpeg"}),
    "png": ("image/png", ".png", {".png"}),
    "webp": ("image/webp", ".webp", {".webp"}),
}


def model_supports_images(model: str) -> bool:
    """保守识别当前已验证可接受 OpenAI image_url 的视觉模型。"""
    name = model.strip().lower().replace("_", "-")
    return any(
        marker in name
        for marker in (
            "qwen3.8-max",
            "qwen3-vl",
            "qwen2.5-vl",
            "qwen2-vl",
            "qwen-vl-max",
            "qwen-vl-plus",
        )
    )


def _png_size(data: bytes) -> tuple[int, int] | None:
    if (
        len(data) >= 45
        and data[:8] == b"\x89PNG\r\n\x1a\n"
        and data[12:16] == b"IHDR"
        and data[-12:] == b"\x00\x00\x00\x00IEND\xaeB`\x82"
    ):
        return struct.unpack(">II", data[16:24])
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
        return None
    offset = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if length < 2 or offset + length > len(data):
            break
        if marker in sof_markers and length >= 7:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    if int.from_bytes(data[4:8], "little") + 8 != len(data):
        return None
    kind = data[12:16]
    if kind == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if kind == b"VP8L" and data[20] == 0x2F:
        b0, b1, b2, b3 = data[21:25]
        width = 1 + b0 + ((b1 & 0x3F) << 8)
        height = 1 + ((b1 & 0xC0) >> 6) + (b2 << 2) + ((b3 & 0x0F) << 10)
        return width, height
    if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    return None


def inspect_image(data: bytes, original_filename: str) -> tuple[str, str, int, int]:
    suffix = Path(original_filename).suffix.lower()
    detected: tuple[str, tuple[int, int] | None] | None = None
    for name, parser in (("png", _png_size), ("jpeg", _jpeg_size), ("webp", _webp_size)):
        size = parser(data)
        if size is not None:
            detected = (name, size)
            break
    if detected is None:
        raise InvalidChatImageError("无法识别图片内容，仅支持 JPG、PNG、WebP")
    name, (width, height) = detected
    mime_type, extension, allowed_suffixes = _FORMATS[name]
    if suffix not in allowed_suffixes:
        raise InvalidChatImageError("图片扩展名与实际格式不一致")
    if width <= 0 or height <= 0:
        raise InvalidChatImageError("图片尺寸无效")
    if width * height > settings.chat_image_max_pixels:
        raise InvalidChatImageError(
            f"图片像素超过限制：最多 {settings.chat_image_max_pixels} 像素"
        )
    return mime_type, extension, width, height


def image_storage_root() -> Path:
    root = Path(settings.chat_image_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_image(data: bytes, extension: str) -> str:
    filename = f"{uuid.uuid4().hex}{extension}"
    (image_storage_root() / filename).write_bytes(data)
    return filename


def resolve_image(stored_filename: str) -> Path:
    root = image_storage_root()
    path = (root / stored_filename).resolve()
    if path.parent != root or not path.is_file():
        raise FileNotFoundError("图片文件不存在")
    return path


def image_data_url(stored_filename: str, mime_type: str) -> str:
    encoded = base64.b64encode(resolve_image(stored_filename).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"

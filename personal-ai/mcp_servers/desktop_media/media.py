"""通过 Windows 全局媒体会话控制 QQ 音乐。"""

from __future__ import annotations

from typing import Any

from mcp_servers.desktop_media.config import DesktopMediaError


QQMUSIC_SOURCE_MARKERS = ("qqmusic", "qq music", "tencent.qqmusic")


async def _request_manager():
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )
    except ImportError as exc:
        raise DesktopMediaError("Windows 媒体控制组件未安装") from exc
    return await GlobalSystemMediaTransportControlsSessionManager.request_async()


def _is_qqmusic_source(source: str) -> bool:
    normalized = source.strip().lower()
    return any(marker in normalized for marker in QQMUSIC_SOURCE_MARKERS)


async def _qqmusic_session():
    manager = await _request_manager()
    sessions = list(manager.get_sessions())
    for session in sessions:
        if _is_qqmusic_source(str(session.source_app_user_model_id or "")):
            return session
    raise DesktopMediaError("QQ 音乐尚未创建系统媒体会话，请先在 QQ 音乐中播放一首歌曲")


def _playback_status_name(session) -> str:
    status = session.get_playback_info().playback_status
    return str(getattr(status, "name", status)).lower()


async def get_current() -> dict[str, Any]:
    session = await _qqmusic_session()
    properties = await session.try_get_media_properties_async()
    return {
        "ok": True,
        "source": str(session.source_app_user_model_id or ""),
        "status": _playback_status_name(session),
        "title": str(properties.title or ""),
        "artist": str(properties.artist or ""),
        "album": str(properties.album_title or ""),
    }


async def play_pause() -> dict[str, Any]:
    session = await _qqmusic_session()
    if _playback_status_name(session) == "playing":
        changed = await session.try_pause_async()
        action = "paused"
    else:
        changed = await session.try_play_async()
        action = "playing"
    if not changed:
        raise DesktopMediaError("QQ 音乐拒绝了播放状态切换")
    return {"ok": True, "action": action}


async def next_track() -> dict[str, Any]:
    session = await _qqmusic_session()
    if not await session.try_skip_next_async():
        raise DesktopMediaError("QQ 音乐当前不允许切换到下一首")
    return {"ok": True, "action": "next"}


async def previous_track() -> dict[str, Any]:
    session = await _qqmusic_session()
    if not await session.try_skip_previous_async():
        raise DesktopMediaError("QQ 音乐当前不允许切换到上一首")
    return {"ok": True, "action": "previous"}

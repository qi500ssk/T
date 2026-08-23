"""受限的 QQ 音乐与 Windows 媒体控制 stdio MCP Server。"""

from __future__ import annotations

import asyncio
import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.desktop_media import media, qqmusic


server = FastMCP("personal-ai-desktop-media", log_level="WARNING")
VERIFY_TIMEOUT_SECONDS = 6.0


def _result(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


@server.tool()
async def qqmusic_launch() -> str:
    """安全地启动或激活本机 QQ 音乐；不接受任意程序路径。"""
    return _result(await asyncio.to_thread(qqmusic.launch))


@server.tool()
async def qqmusic_search_play(song: str, artist: str = "") -> str:
    """在 QQ 音乐中搜索并验证播放。artist 仅在用户明确提供时填写，禁止猜测；失败后不要改用浏览器工具。"""
    result = await asyncio.to_thread(qqmusic.search_and_play, song, artist)
    deadline = asyncio.get_running_loop().time() + VERIFY_TIMEOUT_SECONDS
    current = None
    verification_error = ""
    while asyncio.get_running_loop().time() < deadline:
        try:
            current = await media.get_current()
            if song.casefold() in current["title"].casefold():
                result["current"] = current
                result["verified"] = True
                return _result(result)
        except ValueError as exc:
            verification_error = str(exc)
        await asyncio.sleep(0.4)
    current_label = (
        f"{current.get('title', '')} - {current.get('artist', '')}" if current else verification_error
    )
    raise ValueError(
        "QQ 音乐没有切换到目标歌曲；"
        f"已点击候选“{result['selected_title']} - {result['selected_artist']}”，"
        f"当前仍为“{current_label}”。不要猜测歌手，也不要调用浏览器工具重试。"
    )


@server.tool()
async def qqmusic_list_liked(limit: int = 20) -> str:
    """打开 QQ 音乐“喜欢”并列出当前可见歌曲。要自主选歌时必须先调用此工具，再从结果中选择。"""
    return _result(await asyncio.to_thread(qqmusic.list_liked_songs, limit))


@server.tool()
async def qqmusic_play_liked(
    song: str,
    artist: str = "",
) -> str:
    """播放“喜欢”列表中的指定歌曲；song/artist 必须来自刚读取的列表。"""
    result = await asyncio.to_thread(
        qqmusic.play_liked_song,
        song,
        artist,
    )
    deadline = asyncio.get_running_loop().time() + VERIFY_TIMEOUT_SECONDS
    current = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            current = await media.get_current()
            if song.casefold() in current["title"].casefold():
                result["current"] = current
                result["verified"] = True
                return _result(result)
        except ValueError:
            pass
        await asyncio.sleep(0.4)
    current_label = (
        f"{current.get('title', '')} - {current.get('artist', '')}" if current else "无法读取"
    )
    raise ValueError(
        f"QQ 音乐没有切换到喜欢歌曲“{song}”；当前仍为“{current_label}”。"
        "请重新读取喜欢列表，不要改用浏览器工具重试。"
    )


@server.tool()
async def media_play_pause() -> str:
    """切换 QQ 音乐当前媒体会话的播放或暂停状态。"""
    return _result(await media.play_pause())


@server.tool()
async def media_next() -> str:
    """让 QQ 音乐播放下一首歌曲。"""
    return _result(await media.next_track())


@server.tool()
async def media_previous() -> str:
    """让 QQ 音乐播放上一首歌曲。"""
    return _result(await media.previous_track())


@server.tool()
async def media_get_current() -> str:
    """读取 QQ 音乐当前歌曲、歌手、专辑和播放状态。"""
    return _result(await media.get_current())


if __name__ == "__main__":
    server.run(transport="stdio")

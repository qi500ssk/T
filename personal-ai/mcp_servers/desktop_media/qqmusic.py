"""QQ 音乐启动和基于 Windows UI Automation 的搜索播放。"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from mcp_servers.desktop_media.config import (
    DesktopMediaError,
    discover_qqmusic_executable,
)


SEARCH_MARKERS = ("搜索", "search")
CLICKABLE_CONTROL_TYPES = {"ListItem", "DataItem", "Button", "Hyperlink"}
DESKTOP_LYRICS_TITLE = "桌面歌词"
POST_CLICK_SETTLE_SECONDS = 1.0
LIKES_ENTRY_PREFIX = "喜欢·"
LIKES_PAGE_TITLE = "喜欢"


@dataclass(frozen=True)
class SearchResult:
    title: str
    artist: str
    element: object
    top: int


@dataclass(frozen=True)
class LikedSong:
    title: str
    artist: str
    album: str
    element: object
    top: int


@dataclass(frozen=True)
class WindowState:
    foreground: int
    was_visible: bool
    was_iconic: bool


def _automation():
    try:
        from pywinauto import Application, keyboard
    except ImportError as exc:
        raise DesktopMediaError("Windows UI Automation 组件未安装") from exc
    return Application, keyboard


def _connect_window(executable: Path, timeout: float = 1.0):
    Application, _ = _automation()
    try:
        app = Application(backend="uia").connect(path=str(executable), timeout=timeout)
        windows = list(app.windows())
    except Exception as exc:
        raise DesktopMediaError("QQ 音乐尚未启动或主窗口不可访问") from exc
    windows = [
        window
        for window in windows
        if str(window.window_text() or "").strip() != DESKTOP_LYRICS_TITLE
    ]
    if not windows:
        raise DesktopMediaError("QQ 音乐已运行，但没有可访问的主窗口")
    return max(
        windows,
        key=lambda item: item.rectangle().width() * item.rectangle().height(),
    )


def _focus_window(window) -> None:
    try:
        import win32con
        import win32gui

        win32gui.ShowWindow(window.handle, win32con.SW_RESTORE)
        win32gui.ShowWindow(window.handle, win32con.SW_SHOW)
        time.sleep(0.2)
        window.set_focus()
    except Exception as exc:
        raise DesktopMediaError(
            "无法激活 QQ 音乐窗口；请确认它未以管理员身份运行"
        ) from exc


def _capture_window_state(window, foreground: int | None = None) -> WindowState:
    import win32gui

    return WindowState(
        foreground=foreground or win32gui.GetForegroundWindow(),
        was_visible=bool(win32gui.IsWindowVisible(window.handle)),
        was_iconic=bool(win32gui.IsIconic(window.handle)),
    )


def _restore_foreground(handle: int) -> None:
    if not handle:
        return
    try:
        import win32gui

        if win32gui.IsWindow(handle):
            win32gui.SetForegroundWindow(handle)
    except Exception:
        # Windows may reject foreground changes when another process is busy.
        pass


def _restore_window(window, state: WindowState) -> None:
    try:
        import win32con
        import win32gui

        if state.was_iconic:
            win32gui.ShowWindow(window.handle, win32con.SW_MINIMIZE)
        elif not state.was_visible:
            win32gui.ShowWindow(window.handle, win32con.SW_HIDE)
    finally:
        _restore_foreground(state.foreground)


def launch(wait_seconds: float = 8.0, *, activate: bool = True) -> dict:
    executable = discover_qqmusic_executable()
    try:
        window = _connect_window(executable, timeout=0.5)
        already_running = True
    except DesktopMediaError:
        subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        already_running = False
        deadline = time.monotonic() + wait_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                window = _connect_window(executable, timeout=0.5)
                break
            except DesktopMediaError as exc:
                last_error = exc
                time.sleep(0.25)
        else:
            raise DesktopMediaError("QQ 音乐已启动，但主窗口在限定时间内没有出现") from last_error
    if activate:
        _focus_window(window)
    return {
        "ok": True,
        "already_running": already_running,
        "executable": str(executable),
        "window": str(window.window_text() or "QQ 音乐"),
    }


def _element_text(element) -> str:
    info = element.element_info
    return " ".join(
        str(value or "").strip()
        for value in (info.name, info.automation_id, info.class_name)
        if str(value or "").strip()
    )


def _find_search_box(window):
    candidates = list(window.descendants(control_type="Edit"))
    if len(candidates) == 1:
        # 当前 QQ 音乐桌面版只暴露一个无名称 Edit；唯一时可安全识别。
        return candidates[0]
    ranked = sorted(
        candidates,
        key=lambda item: (
            not any(marker in _element_text(item).lower() for marker in SEARCH_MARKERS),
            len(_element_text(item)),
        ),
    )
    if not ranked or not any(
        marker in _element_text(ranked[0]).lower() for marker in SEARCH_MARKERS
    ):
        discovered = [text for item in candidates if (text := _element_text(item))][:8]
        detail = "、".join(discovered) or "没有 Edit 控件"
        raise DesktopMediaError(f"未识别到 QQ 音乐搜索框；当前可见输入控件：{detail}")
    return ranked[0]


def _send_window_click(window, element, *, double: bool = False) -> None:
    try:
        import win32api
        import win32con
        import win32gui

        rectangle = element.rectangle()
        screen_point = (
            (rectangle.left + rectangle.right) // 2,
            (rectangle.top + rectangle.bottom) // 2,
        )
        client_point = win32gui.ScreenToClient(window.handle, screen_point)
        position = win32api.MAKELONG(*client_point)
        win32gui.SendMessage(
            window.handle,
            win32con.WM_LBUTTONDOWN,
            win32con.MK_LBUTTON,
            position,
        )
        win32gui.SendMessage(
            window.handle,
            win32con.WM_LBUTTONUP,
            0,
            position,
        )
        if double:
            win32gui.SendMessage(
                window.handle,
                win32con.WM_LBUTTONDBLCLK,
                win32con.MK_LBUTTON,
                position,
            )
            win32gui.SendMessage(
                window.handle,
                win32con.WM_LBUTTONUP,
                0,
                position,
            )
    except Exception as exc:
        raise DesktopMediaError("无法向 QQ 音乐控件发送后台点击消息") from exc


def _set_search_text(window, search_box, query: str, keyboard) -> None:
    try:
        # QQ 音乐搜索框是自绘控件，不支持 UIA ValuePattern。向已激活窗口
        # 发送点击消息可以建立内部输入焦点，同时不会移动真实鼠标。
        _send_window_click(window, search_box)
        keyboard.send_keys("^a")
        keyboard.send_keys(query, with_spaces=True)
        keyboard.send_keys("{ENTER}")
    except Exception as exc:
        raise DesktopMediaError("找到了搜索框，但无法输入歌曲名称") from exc


def _matching_result(window, song: str, artist: str) -> SearchResult:
    song_key = song.casefold()
    artist_key = artist.casefold()
    elements = list(window.descendants())
    artist_elements: list[tuple[str, object]] = []
    for item in elements:
        text = str(item.window_text() or item.element_info.name or "").strip()
        if text.startswith("歌手："):
            artist_elements.append((text.removeprefix("歌手：").strip(), item))

    candidates: list[SearchResult] = []
    for item in elements:
        if str(item.element_info.control_type or "") not in {
            "Hyperlink",
            "ListItem",
            "DataItem",
        }:
            continue
        text = str(item.window_text() or item.element_info.name or "").strip()
        normalized = text.casefold()
        if (
            song_key not in normalized
            or text.startswith(("歌手：", "专辑："))
        ):
            continue
        song_rect = item.rectangle()
        nearby_artists: list[tuple[int, str]] = []
        for artist_text, artist_item in artist_elements:
            artist_rect = artist_item.rectangle()
            vertical_gap = artist_rect.top - song_rect.top
            horizontal_gap = abs(artist_rect.left - song_rect.left)
            if 0 <= vertical_gap <= 55 and horizontal_gap <= 180:
                nearby_artists.append((vertical_gap, artist_text))
        row_artist = min(nearby_artists, default=(999, ""))[1]
        if artist_key and artist_key not in row_artist.casefold():
            continue
        candidates.append(
            SearchResult(
                title=text,
                artist=row_artist,
                element=item,
                top=song_rect.top,
            )
        )
    if not candidates:
        available = []
        for item in elements:
            if str(item.element_info.control_type or "") != "Hyperlink":
                continue
            text = str(item.window_text() or item.element_info.name or "").strip()
            if song_key in text.casefold() and not text.startswith(("歌手：", "专辑：")):
                available.append(text)
        choices = f"；可见候选：{'、'.join(available[:5])}" if available else ""
        raise DesktopMediaError(
            f"搜索结果中没有找到歌曲“{song}”"
            + (f"（歌手：{artist}）" if artist else "")
            + choices
        )
    # QQ 音乐已按相关度排序；优先选择页面最靠上的匹配行。
    return min(candidates, key=lambda row: row.top)


def _click_result(window, element) -> None:
    target = element
    for _ in range(4):
        if str(target.element_info.control_type or "") in CLICKABLE_CONTROL_TYPES:
            break
        try:
            target = target.parent()
        except Exception:
            break
    try:
        _send_window_click(window, target, double=True)
    except Exception as exc:
        raise DesktopMediaError("找到了歌曲结果，但无法执行播放操作") from exc


def _find_likes_entry(window):
    candidates = []
    for item in window.descendants():
        text = str(item.window_text() or item.element_info.name or "").strip()
        if text.startswith(LIKES_ENTRY_PREFIX):
            candidates.append(item)
    if not candidates:
        raise DesktopMediaError("未识别到 QQ 音乐侧栏的“喜欢”入口")
    return min(candidates, key=lambda item: item.rectangle().left)


def _is_likes_page(window) -> bool:
    has_title = False
    has_play_all = False
    for item in window.descendants():
        text = str(item.window_text() or item.element_info.name or "").strip()
        if text == LIKES_PAGE_TITLE:
            has_title = True
        elif text == "播放全部":
            has_play_all = True
        if has_title and has_play_all:
            return True
    return False


def _open_likes(window, wait_seconds: float = 3.0) -> None:
    if _is_likes_page(window):
        return
    _send_window_click(window, _find_likes_entry(window))
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _is_likes_page(window):
            return
        time.sleep(0.2)
    raise DesktopMediaError("已点击“喜欢”，但歌曲列表没有在限定时间内打开")


def _liked_song_rows(window) -> list[LikedSong]:
    links = []
    buttons = []
    for item in window.descendants():
        text = str(item.window_text() or item.element_info.name or "").strip()
        if not text:
            continue
        control_type = str(item.element_info.control_type or "")
        if control_type == "Hyperlink":
            links.append((item.rectangle().top, item.rectangle().left, text, item))
        elif control_type == "Button":
            buttons.append((item.rectangle().top, item.rectangle().left, text))
    links.sort(key=lambda row: (row[0], row[1]))

    songs: list[LikedSong] = []
    for top, left, title, element in links:
        artist_candidates = [
            (other_top - top, other_text)
            for other_top, other_left, other_text, _ in links
            if other_left == left and 20 <= other_top - top <= 45
        ]
        if not artist_candidates:
            continue
        _, artist = min(artist_candidates)
        album_candidates = [
            (abs(button_top - top), button_text)
            for button_top, button_left, button_text in buttons
            if button_left > left + 250 and abs(button_top - top) <= 24
        ]
        album = min(album_candidates, default=(999, ""))[1]
        songs.append(
            LikedSong(
                title=title,
                artist=artist,
                album=album,
                element=element,
                top=top,
            )
        )
    if not songs:
        raise DesktopMediaError("“喜欢”页面已打开，但当前没有识别到可播放的歌曲行")
    return songs


def _matching_liked_song(window, song: str, artist: str) -> LikedSong:
    song_key = song.casefold()
    artist_key = artist.casefold()
    matches = [
        item
        for item in _liked_song_rows(window)
        if song_key in item.title.casefold()
        and (not artist_key or artist_key in item.artist.casefold())
    ]
    if not matches:
        raise DesktopMediaError(
            f"当前可见的“喜欢”列表中没有找到歌曲“{song}”"
            + (f"（歌手：{artist}）" if artist else "")
            + "；请先重新读取喜欢列表，再从返回结果中选择"
        )
    exact = [
        item
        for item in matches
        if item.title.casefold() == song_key
        and (not artist_key or item.artist.casefold() == artist_key)
    ]
    return min(exact or matches, key=lambda item: item.top)


def list_liked_songs(limit: int = 20) -> dict:
    if not 1 <= limit <= 50:
        raise DesktopMediaError("读取数量必须在 1 到 50 之间")
    launch_info = launch(activate=False)
    window = _connect_window(Path(launch_info["executable"]), timeout=1.0)
    _open_likes(window)
    songs = _liked_song_rows(window)[:limit]
    return {
        "ok": True,
        "action": "list_liked_songs",
        "count": len(songs),
        "songs": [
            {"title": item.title, "artist": item.artist, "album": item.album}
            for item in songs
        ],
    }


def play_liked_song(
    song: str,
    artist: str = "",
) -> dict:
    song = song.strip()
    artist = artist.strip()
    if not song or len(song) > 120 or len(artist) > 120:
        raise DesktopMediaError("歌曲名不能为空，歌曲名和歌手名均不能超过 120 个字符")
    launch_info = launch(activate=False)
    window = _connect_window(Path(launch_info["executable"]), timeout=1.0)
    _open_likes(window)
    selected = _matching_liked_song(window, song, artist)
    _click_result(window, selected.element)
    time.sleep(POST_CLICK_SETTLE_SECONDS)
    return {
        "ok": True,
        "action": "play_liked_song",
        "selected_title": selected.title,
        "selected_artist": selected.artist,
        "selected_album": selected.album,
        "input_mode": "window_message",
    }


def search_and_play(song: str, artist: str = "", result_wait_seconds: float = 4.0) -> dict:
    song = song.strip()
    artist = artist.strip()
    if not song or len(song) > 120 or len(artist) > 120:
        raise DesktopMediaError("歌曲名不能为空，歌曲名和歌手名均不能超过 120 个字符")
    import win32gui

    original_foreground = win32gui.GetForegroundWindow()
    launch_info = launch(activate=False)
    executable = Path(launch_info["executable"])
    window = _connect_window(executable, timeout=1.0)
    state = _capture_window_state(window, original_foreground)
    if not launch_info["already_running"]:
        state = WindowState(original_foreground, False, True)
    try:
        _focus_window(window)
        _, keyboard = _automation()
        search_box = _find_search_box(window)
        query = " ".join(item for item in (song, artist) if item)
        _set_search_text(window, search_box, query, keyboard)
        _restore_foreground(state.foreground)

        deadline = time.monotonic() + result_wait_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                result = _matching_result(window, song, artist)
                _focus_window(window)
                # 激活窗口后重新定位，避免恢复窗口导致控件坐标变化。
                result = _matching_result(window, song, artist)
                _click_result(window, result.element)
                # 点击消息会同步送达窗口，但 QQ 音乐异步处理实际播放。
                # 先归还前台，再给客户端短暂时间完成切歌，最后由 finally
                # 恢复它原来的显示或最小化状态。
                _restore_foreground(state.foreground)
                time.sleep(POST_CLICK_SETTLE_SECONDS)
                return {
                    "ok": True,
                    "action": "search_play",
                    "song": song,
                    "artist": artist,
                    "query": query,
                    "window": launch_info["window"],
                    "selected_title": result.title,
                    "selected_artist": result.artist,
                    "input_mode": "window_message",
                }
            except DesktopMediaError as exc:
                last_error = exc
                _restore_foreground(state.foreground)
                time.sleep(0.3)
        raise DesktopMediaError(str(last_error or "QQ 音乐搜索结果加载超时"))
    finally:
        _restore_window(window, state)

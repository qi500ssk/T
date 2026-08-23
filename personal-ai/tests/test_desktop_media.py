from pathlib import Path
from types import SimpleNamespace

import pytest

from core.capabilities.mcp import McpClient, load_mcp_configs
from mcp_servers.desktop_media import config, media, qqmusic, server as desktop_server
from mcp_servers.desktop_media.config import DesktopMediaError


def test_configured_qqmusic_path_is_validated(tmp_path, monkeypatch):
    executable = tmp_path / "QQMusic.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("QQMUSIC_EXE", str(executable))
    assert config.discover_qqmusic_executable() == executable.resolve()


def test_configured_qqmusic_path_rejects_other_program(tmp_path, monkeypatch):
    executable = tmp_path / "cmd.exe"
    executable.write_bytes(b"test")
    monkeypatch.setenv("QQMUSIC_EXE", str(executable))
    with pytest.raises(DesktopMediaError, match="QQMusic.exe"):
        config.discover_qqmusic_executable()


class FakeProperties:
    title = "晴天"
    artist = "周杰伦"
    album_title = "叶惠美"


class FakeSession:
    source_app_user_model_id = "Tencent.QQMusic"

    def __init__(self, status="playing"):
        self.status = status
        self.actions: list[str] = []

    def get_playback_info(self):
        return SimpleNamespace(
            playback_status=SimpleNamespace(name=self.status),
        )

    async def try_get_media_properties_async(self):
        return FakeProperties()

    async def try_pause_async(self):
        self.actions.append("pause")
        return True

    async def try_play_async(self):
        self.actions.append("play")
        return True

    async def try_skip_next_async(self):
        self.actions.append("next")
        return True

    async def try_skip_previous_async(self):
        self.actions.append("previous")
        return True

class FakeManager:
    def __init__(self, sessions):
        self.sessions = sessions

    def get_sessions(self):
        return self.sessions


@pytest.mark.asyncio
async def test_media_controls_only_matching_qqmusic_session(monkeypatch):
    other = SimpleNamespace(source_app_user_model_id="Spotify.exe")
    session = FakeSession()

    async def manager():
        return FakeManager([other, session])

    monkeypatch.setattr(media, "_request_manager", manager)
    current = await media.get_current()
    assert current["title"] == "晴天"
    assert current["artist"] == "周杰伦"
    assert (await media.play_pause())["action"] == "paused"
    assert (await media.next_track())["action"] == "next"
    assert (await media.previous_track())["action"] == "previous"
    assert session.actions == ["pause", "next", "previous"]


@pytest.mark.asyncio
async def test_media_control_refuses_to_operate_other_players(monkeypatch):
    async def manager():
        return FakeManager([SimpleNamespace(source_app_user_model_id="Spotify.exe")])

    monkeypatch.setattr(media, "_request_manager", manager)
    with pytest.raises(DesktopMediaError, match="QQ 音乐尚未创建"):
        await media.play_pause()


class FakeElement:
    def __init__(
        self,
        name: str,
        control_type: str,
        parent=None,
        top=0,
        left=0,
        right=100,
        bottom=30,
    ):
        self.element_info = SimpleNamespace(
            name=name,
            automation_id="",
            class_name="",
            control_type=control_type,
        )
        self._parent = parent
        self._rectangle = SimpleNamespace(
            top=top,
            left=left,
            right=right,
            bottom=bottom,
        )

    def window_text(self):
        return self.element_info.name

    def parent(self):
        return self._parent

    def rectangle(self):
        return self._rectangle


class FakeWindow:
    def __init__(self, elements):
        self.elements = elements
        self.handle = 123

    def descendants(self, **kwargs):
        control_type = kwargs.get("control_type")
        if control_type:
            return [item for item in self.elements if item.element_info.control_type == control_type]
        return self.elements


def test_search_result_prefers_song_and_artist_match():
    other = FakeElement("晴天 (Live)", "Hyperlink", top=100, left=200)
    other_artist = FakeElement("歌手：其他歌手", "Hyperlink", top=132, left=200)
    exact = FakeElement("晴天", "Hyperlink", top=200, left=200)
    exact_artist = FakeElement("歌手：周杰伦", "Hyperlink", top=232, left=200)
    selected = qqmusic._matching_result(
        FakeWindow([other, other_artist, exact, exact_artist]), "晴天", "周杰伦"
    )
    assert selected.element is exact
    assert selected.artist == "周杰伦"


def test_search_result_without_artist_uses_top_ranked_row():
    first = FakeElement("女儿国 电影主题曲", "Hyperlink", top=100, left=200)
    first_artist = FakeElement("歌手：张靓颖,李荣浩", "Hyperlink", top=132, left=200)
    live = FakeElement("女儿国 (Live)", "Hyperlink", top=300, left=200)
    live_artist = FakeElement("歌手：其他歌手", "Hyperlink", top=332, left=200)
    selected = qqmusic._matching_result(
        FakeWindow([live, live_artist, first, first_artist]), "女儿国", ""
    )
    assert selected.element is first
    assert selected.artist == "张靓颖,李荣浩"


def test_single_unnamed_edit_is_accepted_as_search_box():
    edit = FakeElement("", "Edit")
    assert qqmusic._find_search_box(FakeWindow([edit])) is edit


def test_multiple_unnamed_edits_are_not_guessed():
    edits = [FakeElement("", "Edit"), FakeElement("", "Edit")]
    with pytest.raises(DesktopMediaError, match="未识别到"):
        qqmusic._find_search_box(FakeWindow(edits))


def test_search_input_uses_window_message_instead_of_mouse(monkeypatch):
    search_box = FakeElement("", "Edit")
    window = FakeWindow([search_box])
    clicks = []

    def window_click(actual_window, actual_element, *, double=False):
        clicks.append((actual_window, actual_element, double))

    class FakeKeyboard:
        def __init__(self):
            self.keys = []

        def send_keys(self, keys, **kwargs):
            self.keys.append((keys, kwargs))

    keyboard = FakeKeyboard()
    monkeypatch.setattr(qqmusic, "_send_window_click", window_click)
    qqmusic._set_search_text(window, search_box, "稻香", keyboard)
    assert clicks == [(window, search_box, False)]
    assert [item[0] for item in keyboard.keys] == ["^a", "稻香", "{ENTER}"]


def test_result_activation_uses_window_message_instead_of_mouse(monkeypatch):
    result = FakeElement("稻香", "Hyperlink")
    window = FakeWindow([result])
    clicks = []

    monkeypatch.setattr(
        qqmusic,
        "_send_window_click",
        lambda actual_window, actual_element, *, double=False: clicks.append(
            (actual_window, actual_element, double)
        ),
    )
    qqmusic._click_result(window, result)
    assert clicks == [(window, result, True)]


def test_likes_entry_prefers_sidebar_count_label():
    row_button = FakeElement("我喜欢", "Button", left=800, top=500)
    sidebar = FakeElement("喜欢·464", "Text", left=20, top=100)
    assert qqmusic._find_likes_entry(FakeWindow([row_button, sidebar])) is sidebar


def test_liked_song_rows_pair_title_artist_and_album():
    title = FakeElement("我不难过", "Hyperlink", left=200, top=100)
    artist = FakeElement("孙燕姿", "Hyperlink", left=200, top=132)
    album = FakeElement("未完成", "Button", left=700, top=113)
    next_title = FakeElement("碎碎念", "Hyperlink", left=200, top=187)
    next_artist = FakeElement("队长", "Hyperlink", left=200, top=219)
    rows = qqmusic._liked_song_rows(
        FakeWindow([title, artist, album, next_title, next_artist])
    )
    assert [(item.title, item.artist, item.album) for item in rows] == [
        ("我不难过", "孙燕姿", "未完成"),
        ("碎碎念", "队长", ""),
    ]


@pytest.mark.asyncio
async def test_desktop_media_mcp_lists_only_restricted_tools():
    config_row = next(
        item for item in load_mcp_configs("config/mcp_servers.yaml")
        if item.name == "desktop-media"
    )
    client = McpClient(config_row, cwd=Path.cwd())
    try:
        await client.connect()
        names = {str(tool.name) for tool in await client.list_tools()}
        assert names == {
            "qqmusic_launch",
            "qqmusic_search_play",
            "qqmusic_list_liked",
            "qqmusic_play_liked",
            "media_play_pause",
            "media_next",
            "media_previous",
            "media_get_current",
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_search_play_fails_when_media_did_not_switch(monkeypatch):
    monkeypatch.setattr(
        desktop_server.qqmusic,
        "search_and_play",
        lambda song, artist: {
            "ok": True,
            "selected_title": "女儿国 电影主题曲",
            "selected_artist": "张靓颖,李荣浩",
        },
    )

    async def unchanged():
        return {"ok": True, "title": "一生所爱", "artist": "卢冠廷/莫文蔚"}

    monkeypatch.setattr(desktop_server.media, "get_current", unchanged)
    monkeypatch.setattr(desktop_server, "VERIFY_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(ValueError, match="没有切换到目标歌曲"):
        await desktop_server.qqmusic_search_play("女儿国")


@pytest.mark.asyncio
async def test_search_play_succeeds_only_after_media_verification(monkeypatch):
    monkeypatch.setattr(
        desktop_server.qqmusic,
        "search_and_play",
        lambda song, artist: {
            "ok": True,
            "selected_title": "女儿国 电影主题曲",
            "selected_artist": "张靓颖,李荣浩",
        },
    )

    async def switched():
        return {"ok": True, "title": "女儿国", "artist": "张靓颖/李荣浩"}

    monkeypatch.setattr(desktop_server.media, "get_current", switched)
    result = await desktop_server.qqmusic_search_play("女儿国")
    assert '"verified": true' in result

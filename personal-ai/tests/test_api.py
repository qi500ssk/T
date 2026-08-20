import json


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """把 SSE 响应文本解析为 [(event, data), ...]。"""
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event, data = "", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        events.append((event, json.loads(data)))
    return events


def test_create_and_list_conversations(client):
    r = client.post("/api/conversations", json={"title": "测试会话"})
    assert r.status_code == 200
    conv = r.json()
    assert conv["title"] == "测试会话"
    rows = client.get("/api/conversations").json()
    assert any(c["id"] == conv["id"] for c in rows)


def test_chat_stream_events(client):
    conv = client.post("/api/conversations", json={}).json()
    r = client.post("/api/chat", json={"conversation_id": conv["id"], "message": "你好"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(r.text)
    types = [e[0] for e in events]
    assert "run.started" in types
    assert "message.delta" in types
    assert "message.completed" in types
    assert "run.completed" in types
    # 事件携带 run_id
    started = dict(events)[
        "run.started"
    ]  # 注意 dict 会覆盖重复 key，此处只取 run.started
    assert started["run_id"]

    # 消息已持久化，会话标题自动取消息前 20 字
    msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == "你好"
    assert msgs[-1]["role"] == "assistant" and msgs[-1]["content"]
    rows = client.get("/api/conversations").json()
    assert [c for c in rows if c["id"] == conv["id"]][0]["title"] == "你好"


def test_chat_unknown_conversation_404(client):
    r = client.post("/api/chat", json={"conversation_id": "nope", "message": "hi"})
    assert r.status_code == 404


def test_rename_and_delete_conversation(client):
    conv = client.post("/api/conversations", json={}).json()
    r = client.patch(f"/api/conversations/{conv['id']}", json={"title": "改名"})
    assert r.status_code == 200 and r.json()["title"] == "改名"
    assert client.delete(f"/api/conversations/{conv['id']}").status_code == 200
    assert client.get("/api/conversations").json() == []


def test_memories_crud(client):
    r = client.post("/api/memories", json={"content": "用户喜欢简洁回答", "kind": "semantic"})
    assert r.status_code == 200
    mem_id = r.json()["id"]
    assert len(client.get("/api/memories").json()) == 1
    assert client.delete(f"/api/memories/{mem_id}").status_code == 200
    assert client.get("/api/memories").json() == []


def test_memory_invalid_kind_422(client):
    r = client.post("/api/memories", json={"content": "x", "kind": "bad"})
    assert r.status_code == 422


def test_duplicate_manual_memory_returns_409(client):
    body = {"content": "用户喜欢简洁回答", "kind": "semantic"}
    assert client.post("/api/memories", json=body).status_code == 200
    duplicate = client.post("/api/memories", json=body)
    assert duplicate.status_code == 409
    assert len(client.get("/api/memories").json()) == 1


def test_sensitive_memory_create_and_update_are_rejected(client):
    rejected = client.post(
        "/api/memories",
        json={"content": "我的 API Key 是 sk-abcdefghijklmnop", "kind": "profile"},
    )
    assert rejected.status_code == 422
    assert client.get("/api/memories").json() == []

    memory = client.post(
        "/api/memories",
        json={"content": "用户喜欢简洁回答", "kind": "profile"},
    ).json()
    rejected_update = client.patch(
        f"/api/memories/{memory['id']}",
        json={"content": "用户手机号是 13812345678"},
    )
    assert rejected_update.status_code == 422
    rows = client.get("/api/memories").json()
    assert rows[0]["content"] == "用户喜欢简洁回答"


def test_memory_auto_extract_and_deduplicate(client):
    conv = client.post("/api/conversations", json={}).json()
    body = {"conversation_id": conv["id"], "message": "我喜欢无糖拿铁。"}
    assert client.post("/api/chat", json=body).status_code == 200
    assert client.post("/api/chat", json=body).status_code == 200

    memories = client.get("/api/memories").json()
    assert len(memories) == 1
    assert memories[0]["content"] == "用户喜欢无糖拿铁"
    assert memories[0]["kind"] == "profile"
    assert memories[0]["importance"] == 4


def test_memory_update_and_disable(client):
    memory = client.post(
        "/api/memories",
        json={"content": "用户喜欢简洁回答", "kind": "semantic", "importance": 3},
    ).json()
    updated = client.patch(
        f"/api/memories/{memory['id']}",
        json={"content": "用户喜欢非常简洁的回答", "importance": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "用户喜欢非常简洁的回答"
    assert updated.json()["importance"] == 5

    disabled = client.post(f"/api/memories/{memory['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False


def test_conversation_summary_is_generated(client, monkeypatch):
    from infrastructure.config import settings

    monkeypatch.setattr(settings, "summary_trigger_messages", 2)
    monkeypatch.setattr(settings, "summary_keep_recent_messages", 1)
    conv = client.post("/api/conversations", json={}).json()
    client.post("/api/chat", json={"conversation_id": conv["id"], "message": "总结这次讨论"})

    row = next(item for item in client.get("/api/conversations").json() if item["id"] == conv["id"])
    assert row["summary"]


def test_postprocess_failure_does_not_fail_chat(client):
    from core.gateway import MockProvider

    class BrokenPostprocessProvider(MockProvider):
        async def complete(self, messages, temperature=0.0):
            raise RuntimeError("postprocess unavailable")

    client.app.state.provider = BrokenPostprocessProvider(delay=0)
    conv = client.post("/api/conversations", json={}).json()
    response = client.post(
        "/api/chat",
        json={"conversation_id": conv["id"], "message": "正常聊天"},
    )
    types = [event for event, _ in parse_sse(response.text)]
    assert "run.completed" in types
    assert "run.failed" not in types


def test_tools_list(client):
    response = client.get("/api/tools")
    assert response.status_code == 200
    tools = {item["name"]: item for item in response.json()}
    assert set(tools) == {"get_time", "calculate", "read_file", "write_file"}
    assert tools["write_file"]["risk_level"] == "high"


def test_unknown_approval_returns_404(client):
    response = client.post(
        "/api/approval",
        json={"approval_id": "0" * 32, "approved": True},
    )
    assert response.status_code == 404

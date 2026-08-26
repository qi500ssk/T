import json

from infrastructure.database import AgentRun, Message, SessionLocal, ToolRun

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


def test_local_frontend_origins_allow_cors_preflight(client):
    for origin in ("http://localhost:4321", "http://127.0.0.1:4321"):
        response = client.options(
            "/api/memories/test",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_create_and_list_conversations(client):
    r = client.post("/api/conversations", json={"title": "测试会话"})
    assert r.status_code == 200
    conv = r.json()
    assert conv["title"] == "测试会话"
    rows = client.get("/api/conversations").json()
    assert any(c["id"] == conv["id"] for c in rows)


def test_conversation_cache_stats_are_token_weighted_and_persisted(client):
    conv = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        session.add_all(
            [
                AgentRun(
                    conversation_id=conv["id"],
                    status="completed",
                    input_tokens=100,
                    cached_input_tokens=50,
                ),
                AgentRun(
                    conversation_id=conv["id"],
                    status="completed",
                    input_tokens=300,
                    cached_input_tokens=240,
                ),
                # 上游没有返回缓存字段时不应被误算成 0% 命中。
                AgentRun(
                    conversation_id=conv["id"],
                    status="completed",
                    input_tokens=1_000,
                    cached_input_tokens=None,
                ),
                AgentRun(
                    conversation_id=conv["id"],
                    status="failed",
                    input_tokens=100,
                    cached_input_tokens=100,
                ),
            ]
        )
        session.commit()

    stats = client.get(f"/api/conversations/{conv['id']}/runs/stats")
    assert stats.status_code == 200
    assert stats.json() == {
        "eligible_run_count": 2,
        "input_tokens": 400,
        "cached_input_tokens": 290,
        "average_cache_hit_rate": 72.5,
    }


def test_projects_group_tasks_and_protect_non_empty_project(client, tmp_path):
    project = client.post(
        "/api/projects",
        json={"name": "个人网站", "workspace_dir": str(tmp_path)},
    )
    assert project.status_code == 200
    project = project.json()

    conversation = client.post(
        "/api/conversations",
        json={"title": "实现首页", "project_id": project["id"]},
    )
    assert conversation.status_code == 200
    assert conversation.json()["project_id"] == project["id"]
    assert client.get("/api/projects").json()[0]["name"] == "个人网站"
    assert client.delete(f"/api/projects/{project['id']}").status_code == 409

    assert client.delete(f"/api/conversations/{conversation.json()['id']}").status_code == 200
    assert client.delete(f"/api/projects/{project['id']}").status_code == 200


def test_remove_project_deletes_its_conversations(client, tmp_path):
    project = client.post(
        "/api/projects",
        json={"name": "小说", "workspace_dir": str(tmp_path)},
    ).json()
    conversation = client.post(
        "/api/conversations",
        json={"title": "继续写第一章", "project_id": project["id"]},
    ).json()

    removed = client.delete(
        f"/api/projects/{project['id']}",
        params={"delete_conversations": True},
    )

    assert removed.status_code == 200
    assert client.get("/api/projects").json() == []
    rows = client.get("/api/conversations").json()
    assert all(row["id"] != conversation["id"] for row in rows)


def test_conversation_rejects_unknown_project(client):
    response = client.post("/api/conversations", json={"project_id": "missing"})
    assert response.status_code == 404


def test_chat_stream_events(client):
    conv = client.post("/api/conversations", json={}).json()
    r = client.post("/api/chat", json={"conversation_id": conv["id"], "message": "你好"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(r.text)
    types = [e[0] for e in events]
    assert "run.started" in types
    assert "context.started" in types
    assert "context.completed" in types
    assert "model.started" in types
    assert "message.delta" in types
    assert "message.completed" in types
    assert "run.completed" in types
    assert types.index("run.started") < types.index("context.started")
    assert types.index("context.completed") < types.index("model.started")
    # 事件携带 run_id
    started = dict(events)[
        "run.started"
    ]  # 注意 dict 会覆盖重复 key，此处只取 run.started
    assert started["run_id"]
    context = dict(events)["context.completed"]
    assert context["context_window_tokens"] > context["max_output_tokens"]
    assert context["input_budget_tokens"] == (
        context["context_window_tokens"] - context["max_output_tokens"]
    )
    assert context["remaining_tokens"] == (
        context["input_budget_tokens"] - context["token_estimate"]
    )
    assert context["conversation_token_estimate"] > 0

    # 消息已持久化，会话标题自动取消息前 20 字
    msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == "你好"
    assert msgs[0]["status"] == "completed"
    assert msgs[0]["token_estimate"] > 0
    assert msgs[-1]["role"] == "assistant" and msgs[-1]["content"]
    assert msgs[-1]["status"] == "completed"
    assert msgs[-1]["run_id"] == started["run_id"]
    rows = client.get("/api/conversations").json()
    assert [c for c in rows if c["id"] == conv["id"]][0]["title"] == "你好"

    # Run 的处理摘要会持久化，刷新或切换会话后仍能恢复为折叠记录。
    history = client.get(f"/api/conversations/{conv['id']}/runs/history")
    assert history.status_code == 200
    run = history.json()[0]
    assert run["id"] == started["run_id"]
    assert run["input_message"] == "你好"
    assert run["status"] == "completed"
    assert run["intent"]
    assert run["context_stats"]["conversation_token_estimate"] > 0
    assert run["input_tokens"] > 0
    assert run["tools"] == []


def test_run_history_includes_tool_records(client):
    conv = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        run = AgentRun(
            conversation_id=conv["id"],
            execution_mode="direct",
            status="completed",
            input_tokens=120,
            output_tokens=30,
        )
        session.add(run)
        session.flush()
        session.add(
            ToolRun(
                run_id=run.id,
                conversation_id=conv["id"],
                tool_call_id="call-history-test",
                step_index=0,
                tool="write_file",
                args_summary='path="notes.md", content_bytes=12',
                result_summary="notes.md",
                risk_level="high",
                status="completed",
                duration_ms=25,
            )
        )
        session.commit()
        run_id = run.id

    history = client.get(f"/api/conversations/{conv['id']}/runs/history")
    assert history.status_code == 200
    run = history.json()[0]
    assert run["id"] == run_id
    assert run["tools"] == [
        {
            "id": run["tools"][0]["id"],
            "tool": "write_file",
            "args_summary": 'path="notes.md", content_bytes=12',
            "result_summary": "notes.md",
            "risk_level": "high",
            "status": "completed",
            "duration_ms": 25,
        }
    ]


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


def test_project_memory_requires_existing_project(client):
    missing = client.post(
        "/api/memories",
        json={
            "content": "项目使用 PostgreSQL",
            "kind": "semantic",
            "scope_type": "project",
            "scope_key": "missing-project",
        },
    )
    assert missing.status_code == 404

    project = client.post(
        "/api/projects", json={"name": "JQ", "workspace_dir": "E:/Pycharm/JQ"}
    ).json()
    created = client.post(
        "/api/memories",
        json={
            "content": "项目使用 PostgreSQL",
            "kind": "semantic",
            "scope_type": "project",
            "scope_key": project["id"],
        },
    )
    assert created.status_code == 200
    assert created.json()["scope_key"] == project["id"]


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


def test_memory_revision_history_scope_filters_and_expiry(client):
    project = client.post(
        "/api/projects", json={"name": "JQ", "workspace_dir": "E:/Pycharm/JQ"}
    ).json()
    original = client.post(
        "/api/memories",
        json={"content": "项目使用 SQLite", "kind": "semantic"},
    ).json()
    revised = client.patch(
        f"/api/memories/{original['id']}",
        json={
            "content": "项目使用 PostgreSQL + pgvector",
            "scope_type": "project",
            "scope_key": project["id"],
        },
    )
    assert revised.status_code == 200
    current = revised.json()
    assert current["id"] != original["id"]
    assert current["supersedes_id"] == original["id"]
    assert current["scope_type"] == "project"

    active = client.get(
        "/api/memories", params={"scope_type": "project", "scope_key": project["id"]}
    ).json()
    assert [row["id"] for row in active] == [current["id"]]
    history = client.get(f"/api/memories/{current['id']}/history").json()
    assert [row["id"] for row in history] == [current["id"], original["id"]]
    assert history[1]["status"] == "superseded"

    expired = client.post(f"/api/memories/{current['id']}/expire")
    assert expired.status_code == 200
    assert expired.json()["status"] == "expired"
    assert expired.json()["expires_at"] is not None
    assert client.get("/api/memories").json() == []
    all_rows = client.get("/api/memories", params={"status": "all"}).json()
    assert {row["status"] for row in all_rows} == {"superseded", "expired"}


def test_memory_revision_accepts_long_local_embedding_model_path(client):
    provider = client.app.state.embedding_provider
    original_model_name = provider.model_name
    provider.model_name = "C:/Users/test/.cache/modelscope/models/" + "local-model/" * 12
    try:
        original = client.post(
            "/api/memories",
            json={"content": "项目原先使用 SQLite", "kind": "semantic"},
        )
        assert original.status_code == 200

        revised = client.patch(
            f"/api/memories/{original.json()['id']}",
            json={"content": "项目现在使用 PostgreSQL + pgvector"},
        )
        assert revised.status_code == 200
        assert revised.json()["supersedes_id"] == original.json()["id"]
    finally:
        provider.model_name = original_model_name


def test_explicit_remember_chat_writes_database_not_file(client):
    from infrastructure.database import ToolRun, SessionLocal

    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        "/api/chat",
        json={
            "conversation_id": conversation["id"],
            "message": "请记住我喜欢无糖拿铁",
        },
    )
    assert response.status_code == 200
    memories = client.get("/api/memories").json()
    assert len(memories) == 1
    assert memories[0]["content"] == "我喜欢无糖拿铁"
    assert memories[0]["kind"] == "profile"
    assert memories[0]["scope_type"] == "global"

    with SessionLocal() as session:
        tools = [row.tool for row in session.query(ToolRun).all()]
    assert "memory_create" in tools
    assert "write_file" not in tools


def test_explicit_memory_chat_can_correct_and_forget(client):
    conversation = client.post("/api/conversations", json={}).json()
    for message in (
        "请记住我喜欢红茶",
        "把你记住的我喜欢红茶改成我喜欢绿茶",
    ):
        response = client.post(
            "/api/chat",
            json={"conversation_id": conversation["id"], "message": message},
        )
        assert response.status_code == 200

    active = client.get("/api/memories").json()
    assert len(active) == 1
    assert active[0]["content"] == "我喜欢绿茶"
    history = client.get(f"/api/memories/{active[0]['id']}/history").json()
    assert [row["content"] for row in history] == ["我喜欢绿茶", "我喜欢红茶"]

    forgotten = client.post(
        "/api/chat",
        json={"conversation_id": conversation["id"], "message": "忘记我喜欢绿茶"},
    )
    assert forgotten.status_code == 200
    current = client.get("/api/memories").json()
    assert len(current) == 1
    assert current[0]["is_active"] is False


def test_conversation_summary_is_generated(client, monkeypatch):
    from infrastructure.config import settings

    monkeypatch.setattr(settings, "summary_trigger_messages", 2)
    monkeypatch.setattr(settings, "summary_keep_recent_messages", 1)
    conv = client.post("/api/conversations", json={}).json()
    client.post("/api/chat", json={"conversation_id": conv["id"], "message": "总结这次讨论"})

    row = next(item for item in client.get("/api/conversations").json() if item["id"] == conv["id"])
    assert row["summary"]


def test_postprocess_failure_does_not_fail_chat(client):
    from core.chat.gateway import MockProvider

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
    assert set(tools) == {
        "get_time", "calculate", "read_file", "write_file", "skill_load",
        "code_list_files", "code_search", "code_read", "code_create_file",
        "code_edit", "code_git_diff", "code_run_check", "memory_list",
        "memory_create", "memory_update", "memory_forget",
    }
    assert tools["skill_load"]["risk_level"] == "low"
    assert tools["write_file"]["risk_level"] == "high"


def test_unknown_approval_returns_404(client):
    response = client.post(
        "/api/approval",
        json={"approval_id": "0" * 32, "approved": True},
    )
    assert response.status_code == 404


def test_unknown_or_invalid_chat_cancel_is_rejected(client):
    assert client.post(f"/api/chat/{'0' * 32}/cancel").status_code == 404
    assert client.post("/api/chat/not-a-run/cancel").status_code == 422


def test_current_run_exposes_direct_interruption_for_frontend_card(client):
    conversation = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        message = Message(
            conversation_id=conversation["id"],
            role="user",
            content="继续分析这个问题",
        )
        session.add(message)
        session.flush()
        run = AgentRun(
            conversation_id=conversation["id"],
            input_message_id=message.id,
            execution_mode="direct",
            status="interrupted",
            error="应用重启或运行进程中断",
        )
        session.add(run)
        session.commit()
        run_id = run.id

    response = client.get(f"/api/conversations/{conversation['id']}/runs/current")
    assert response.status_code == 200
    assert response.json() == {
        "id": run_id,
        "conversation_id": conversation["id"],
        "execution_mode": "direct",
        "status": "interrupted",
        "input_message": "继续分析这个问题",
        "error": "应用重启或运行进程中断",
        "has_checkpoint": False,
        "created_at": response.json()["created_at"],
    }


def test_completed_retry_hides_older_interrupted_run_card(client):
    conversation = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        interrupted = AgentRun(
            id="1" * 32,
            conversation_id=conversation["id"],
            execution_mode="direct",
            status="interrupted",
        )
        completed = AgentRun(
            id="2" * 32,
            conversation_id=conversation["id"],
            execution_mode="direct",
            status="completed",
        )
        session.add_all([interrupted, completed])
        session.flush()
        completed.created_at = interrupted.created_at
        session.commit()

    response = client.get(f"/api/conversations/{conversation['id']}/runs/current")
    assert response.status_code == 200
    assert response.json() is None


def test_cancel_stale_database_run_releases_conversation_lock(client):
    conversation = client.post("/api/conversations", json={}).json()
    with SessionLocal() as session:
        run = AgentRun(conversation_id=conversation["id"], status="running")
        session.add(run)
        session.commit()
        run_id = run.id

    response = client.post(f"/api/chat/{run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "interrupted"
    with SessionLocal() as session:
        assert session.get(AgentRun, run_id).status == "interrupted"
    retry = client.post(
        "/api/chat",
        json={"conversation_id": conversation["id"], "message": "重新回答"},
    )
    assert retry.status_code == 200
    assert "run.completed" in [event for event, _ in parse_sse(retry.text)]

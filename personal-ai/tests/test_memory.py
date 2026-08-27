import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from core.chat.memory import (
    MemoryCandidate,
    contains_sensitive_information,
    extract_memories,
    mark_memories_used,
    retrieve_memories,
    save_memories,
)
from infrastructure.database import Memory, SessionLocal


def _candidate(
    key: str,
    content: str,
    scope: str = "conversation",
    importance: int = 4,
    confidence: float = 0.9,
) -> MemoryCandidate:
    return MemoryCandidate(
        key=key,
        kind="semantic",
        content=content,
        importance=importance,
        confidence=confidence,
        scope_type=scope,
    )


@pytest.mark.parametrize(
    "content",
    [
        "密码是 correct-horse-battery-staple",
        "API_KEY=sk-abcdefghijklmnop",
        "身份证号 11010519491231002X",
        "手机号 13812345678",
        "邮箱 user@example.com",
        "银行卡 6222 0212 3456 7890",
        "-----BEGIN PRIVATE KEY-----",
    ],
)
def test_sensitive_information_patterns(content):
    assert contains_sensitive_information(content)


def test_database_enforces_unique_user_memory_key():
    with SessionLocal() as session:
        session.add_all(
            [
                Memory(user_id="default", normalized_key="preference.coffee", content="A"),
                Memory(user_id="default", normalized_key="preference.coffee", content="B"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_sensitive_candidate_is_not_saved():
    candidate = MemoryCandidate(
        key="credential.api",
        kind="profile",
        content="用户的 API Key 是 sk-abcdefghijklmnop",
        importance=5,
        confidence=1.0,
    )
    with SessionLocal() as session:
        assert save_memories(session, [candidate], "default", "c1", 3, 0.7) == 0
        assert session.query(Memory).count() == 0


def test_saved_memory_keeps_embedding_metadata():
    class EmbeddingProvider:
        model_name = "test-embedding"
        dimension = 512

        def embed_documents(self, texts):
            assert texts == ["用户喜欢深色主题"]
            return [[1.0, *([0.0] * 511)]]

    candidate = MemoryCandidate(
        key="preference.theme",
        kind="profile",
        content="用户喜欢深色主题",
        importance=5,
        confidence=1.0,
    )
    with SessionLocal() as session:
        assert save_memories(
            session,
            [candidate],
            "default",
            "c1",
            3,
            0.7,
            EmbeddingProvider(),
        ) == 1
        memory = session.query(Memory).one()
        assert list(memory.embedding) == [1.0, *([0.0] * 511)]
        assert memory.embedding_model == "test-embedding"
        assert memory.embedding_dim == 512
        assert memory.embedded_at is not None


@pytest.mark.asyncio
async def test_user_opt_out_skips_model_call():
    class Provider:
        called = False

        async def complete(self, messages, temperature=0.0):
            self.called = True
            return json.dumps({"memories": []})

    provider = Provider()
    result = await extract_memories(provider, "不要记住我喜欢咖啡", "好的")
    assert result == []
    assert provider.called is False


@pytest.mark.asyncio
async def test_extract_memories_parses_scope_conservatively():
    class Provider:
        async def complete(self, messages, temperature=0.0):
            return json.dumps(
                {
                    "memories": [
                        {
                            "key": "preference.detail",
                            "kind": "profile",
                            "scope": "global",
                            "content": "用户喜欢中文回答",
                            "importance": 4,
                            "confidence": 0.9,
                        },
                        {
                            "key": "db.engine",
                            "kind": "semantic",
                            "scope": "galaxy",
                            "content": "数据库使用 PostgreSQL",
                            "importance": 4,
                            "confidence": 0.9,
                        },
                    ]
                },
                ensure_ascii=False,
            )

    candidates = await extract_memories(Provider(), "以后都用中文回答", "好的")
    assert [candidate.scope_type for candidate in candidates] == ["agent", "conversation"]


def test_same_key_can_exist_in_different_project_scopes():
    with SessionLocal() as session:
        saved_a = save_memories(
            session,
            [_candidate("db.engine", "JQ 项目数据库使用 PostgreSQL", scope="project")],
            "default",
            "c-a",
            3,
            0.7,
            project_id="proj-a",
        )
        saved_b = save_memories(
            session,
            [_candidate("db.engine", "其他项目数据库使用 SQLite", scope="project")],
            "default",
            "c-b",
            3,
            0.7,
            project_id="proj-b",
        )
        assert (saved_a, saved_b) == (1, 1)
        rows = session.query(Memory).filter(Memory.normalized_key == "db.engine").all()
        assert len(rows) == 2

        recalled = retrieve_memories(
            session, "default", "数据库用什么", 5, conversation_id="c-a", project_id="proj-a"
        )
        contents = [memory.content for memory in recalled]
        assert any("PostgreSQL" in content for content in contents)
        assert not any("SQLite" in content for content in contents)


def test_agent_memories_are_isolated_while_public_and_project_memories_are_shared():
    with SessionLocal() as session:
        assert save_memories(
            session,
            [_candidate("relationship.address", "雷姆称呼用户为昴大人", scope="agent")],
            "default",
            "conv-rem",
            3,
            0.7,
            agent_id="rem",
        ) == 1
        assert save_memories(
            session,
            [_candidate("relationship.address", "波奇称呼用户为前辈", scope="agent")],
            "default",
            "conv-bocchi",
            3,
            0.7,
            agent_id="bocchi",
        ) == 1
        assert save_memories(
            session,
            [_candidate("user.language", "用户希望所有好友使用中文", scope="global")],
            "default",
            "conv-rem",
            3,
            0.7,
            agent_id="rem",
        ) == 1
        assert save_memories(
            session,
            [_candidate("project.database", "共享项目使用 PostgreSQL", scope="project")],
            "default",
            "conv-rem",
            3,
            0.7,
            project_id="shared-project",
            agent_id="rem",
        ) == 1

        rem_rows = retrieve_memories(
            session,
            "default",
            "称呼 中文 PostgreSQL",
            10,
            conversation_id="conv-rem",
            project_id="shared-project",
            agent_id="rem",
        )
        bocchi_rows = retrieve_memories(
            session,
            "default",
            "称呼 中文 PostgreSQL",
            10,
            conversation_id="conv-bocchi",
            project_id="shared-project",
            agent_id="bocchi",
        )

    rem_contents = {row.content for row in rem_rows}
    bocchi_contents = {row.content for row in bocchi_rows}
    assert "雷姆称呼用户为昴大人" in rem_contents
    assert "波奇称呼用户为前辈" not in rem_contents
    assert "波奇称呼用户为前辈" in bocchi_contents
    assert "雷姆称呼用户为昴大人" not in bocchi_contents
    assert "用户希望所有好友使用中文" in rem_contents & bocchi_contents
    assert "共享项目使用 PostgreSQL" in rem_contents & bocchi_contents


def test_new_fact_supersedes_old_with_traceability():
    with SessionLocal() as session:
        assert (
            save_memories(session, [_candidate("db.engine", "项目数据库使用 SQLite")], "default", "c1", 3, 0.7)
            == 1
        )
        assert (
            save_memories(session, [_candidate("db.engine", "项目已经迁移到 PostgreSQL")], "default", "c1", 3, 0.7)
            == 1
        )
        old = session.query(Memory).filter(Memory.status == "superseded").one()
        new = session.query(Memory).filter(Memory.status == "active").one()
        assert old.normalized_key.startswith("superseded.")
        assert new.supersedes_id == old.id
        assert new.content == "项目已经迁移到 PostgreSQL"

        recalled = retrieve_memories(session, "default", "项目数据库是什么", 5, conversation_id="c1")
        assert [memory.id for memory in recalled] == [new.id]


def test_identical_content_is_not_saved_twice():
    with SessionLocal() as session:
        assert (
            save_memories(session, [_candidate("preference.theme", "用户喜欢深色主题")], "default", "c1", 3, 0.7)
            == 1
        )
        assert (
            save_memories(session, [_candidate("preference.theme", "用户喜欢深色主题")], "default", "c1", 3, 0.7)
            == 0
        )
        assert session.query(Memory).count() == 1


def test_content_hash_deduplicates_different_keys_without_embedding():
    with SessionLocal() as session:
        first = save_memories(
            session,
            [_candidate("preference.theme", "用户喜欢深色主题")],
            "default",
            "c1",
            3,
            0.7,
        )
        second = save_memories(
            session,
            [_candidate("preference.dark", "用户喜欢深色主题")],
            "default",
            "c1",
            3,
            0.7,
        )
        assert (first, second) == (1, 0)
        assert session.query(Memory).count() == 1


def test_near_duplicate_in_conversation_does_not_block_global_promotion():
    class EmbeddingProvider:
        model_name = "test-embedding"
        dimension = 512

        def embed_documents(self, texts):
            return [[1.0, *([0.0] * 511)] for _ in texts]

    with SessionLocal() as session:
        assert save_memories(
            session,
            [_candidate("preference.theme", "用户喜欢深色主题")],
            "default",
            "c1",
            3,
            0.7,
            EmbeddingProvider(),
        ) == 1
        assert save_memories(
            session,
            [_candidate("preference.theme", "用户喜欢深色主题", scope="global")],
            "default",
            "c1",
            3,
            0.7,
            EmbeddingProvider(),
        ) == 1
        assert {
            (row.scope_type, row.scope_key)
            for row in session.query(Memory).all()
        } == {("conversation", "c1"), ("global", "global")}


def test_semantic_near_duplicate_is_skipped():
    class EmbeddingProvider:
        model_name = "test-embedding"
        dimension = 512

        def embed_documents(self, texts):
            return [[1.0, *([0.0] * 511)] for _ in texts]

    with SessionLocal() as session:
        first = save_memories(
            session,
            [_candidate("preference.theme", "用户喜欢深色主题")],
            "default",
            "c1",
            3,
            0.7,
            EmbeddingProvider(),
        )
        second = save_memories(
            session,
            [_candidate("preference.dark", "用户喜欢深色主题")],
            "default",
            "c1",
            3,
            0.7,
            EmbeddingProvider(),
        )
        assert (first, second) == (1, 0)
        assert session.query(Memory).count() == 1


def test_project_scope_falls_back_to_conversation_without_project():
    with SessionLocal() as session:
        save_memories(
            session,
            [_candidate("db.engine", "数据库使用 PostgreSQL", scope="project")],
            "default",
            "c1",
            3,
            0.7,
        )
        memory = session.query(Memory).one()
        assert (memory.scope_type, memory.scope_key) == ("conversation", "c1")


def test_expired_and_superseded_memories_are_excluded():
    with SessionLocal() as session:
        session.add_all(
            [
                Memory(
                    user_id="default",
                    normalized_key="expired.fact",
                    content="过期的数据库约定",
                    scope_type="conversation",
                    scope_key="c1",
                    expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                ),
                Memory(
                    user_id="default",
                    normalized_key="superseded.fact",
                    content="被替换的数据库约定",
                    scope_type="conversation",
                    scope_key="c1",
                    status="superseded",
                ),
                Memory(
                    user_id="default",
                    normalized_key="active.fact",
                    content="有效的数据库约定",
                    scope_type="conversation",
                    scope_key="c1",
                ),
            ]
        )
        session.commit()
        recalled = retrieve_memories(session, "default", "数据库约定是什么", 5, conversation_id="c1")
        contents = [memory.content for memory in recalled]
        assert "有效的数据库约定" in contents
        assert "过期的数据库约定" not in contents
        assert "被替换的数据库约定" not in contents


def test_mark_memories_used_updates_feedback():
    with SessionLocal() as session:
        save_memories(session, [_candidate("preference.theme", "用户喜欢深色主题")], "default", "c1", 3, 0.7)
        memory = session.query(Memory).one()
        assert mark_memories_used(session, []) == 0
        assert mark_memories_used(session, [memory.id]) == 1
        session.refresh(memory)
        assert memory.usage_count == 1
        assert memory.last_used_at is not None

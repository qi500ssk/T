import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from core.memory import (
    MemoryCandidate,
    contains_sensitive_information,
    extract_memories,
    save_memories,
)
from infrastructure.database import Memory, SessionLocal
from infrastructure import database


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


def test_existing_sqlite_duplicate_keys_are_migrated(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = create_engine(url)
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE memories ("
                "id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(64), content TEXT, "
                "normalized_key VARCHAR(200), is_active BOOLEAN, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO memories VALUES "
                "('old', 'default', '旧偏好', 'preference.coffee', 1, "
                "'2026-01-01', '2026-01-01'), "
                "('new', 'default', '新偏好', 'preference.coffee', 1, "
                "'2026-02-01', '2026-02-01')"
            )
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(database.settings, "database_url", url)
    database._migrate_sqlite_p1()

    with legacy_engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, normalized_key, is_active FROM memories ORDER BY id")
        ).mappings().all()
        assert rows[1]["id"] == "old"
        assert rows[1]["normalized_key"] == "duplicate.old"
        assert rows[1]["is_active"] == 0
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO memories "
                    "(id, user_id, content, normalized_key, is_active, created_at, updated_at) "
                    "VALUES ('third', 'default', '重复', 'preference.coffee', 1, "
                    "'2026-03-01', '2026-03-01')"
                )
            )


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

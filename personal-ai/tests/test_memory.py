import json

import pytest
from sqlalchemy.exc import IntegrityError

from core.chat.memory import (
    MemoryCandidate,
    contains_sensitive_information,
    extract_memories,
    save_memories,
)
from infrastructure.database import Memory, SessionLocal


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

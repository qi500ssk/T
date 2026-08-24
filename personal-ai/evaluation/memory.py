"""阶段 D 固定记忆评测：仅操作 5433 隔离测试库中的专用评测用户。"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://personal_ai:personal_ai_test_local@localhost:5433/personal_ai_test",
)
if not os.environ["DATABASE_URL"].rstrip("/").endswith("/personal_ai_test"):
    raise RuntimeError("记忆评测只允许连接 personal_ai_test 数据库")

from core.chat.context import build_context  # noqa: E402
from core.chat.memory import MemoryCandidate, retrieve_memories, save_memories  # noqa: E402
from core.rag.embedding import MockEmbeddingProvider  # noqa: E402
from infrastructure.config import settings  # noqa: E402
from infrastructure.database import (  # noqa: E402
    Conversation,
    Memory,
    Project,
    SessionLocal,
    init_db,
)


ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / "tests" / "eval" / "memory_cases.json"
EVAL_USER = "evaluation-memory"


def _clean(session) -> None:
    session.query(Memory).filter(Memory.user_id == EVAL_USER).delete(
        synchronize_session=False
    )
    session.query(Conversation).filter(Conversation.user_id == EVAL_USER).delete(
        synchronize_session=False
    )
    session.query(Project).filter(Project.user_id == EVAL_USER).delete(
        synchronize_session=False
    )
    session.commit()


def _seed(session, provider) -> dict[str, Conversation]:
    alpha_project = Project(user_id=EVAL_USER, name="eval-memory-alpha")
    beta_project = Project(user_id=EVAL_USER, name="eval-memory-beta")
    session.add_all([alpha_project, beta_project])
    session.flush()
    alpha = Conversation(user_id=EVAL_USER, project_id=alpha_project.id, title="eval-alpha")
    beta = Conversation(user_id=EVAL_USER, project_id=beta_project.id, title="eval-beta")
    session.add_all([alpha, beta])
    session.flush()

    save_memories(
        session,
        [
            MemoryCandidate("project.database", "semantic", "项目数据库使用 SQLite", 5, 1.0, "project"),
            MemoryCandidate("response.language", "profile", "用户偏好使用中文回答", 5, 1.0, "global"),
            MemoryCandidate("conversation.code", "episodic", "当前会话代号是 A-17", 4, 1.0, "conversation"),
        ],
        EVAL_USER,
        alpha.id,
        3,
        0.7,
        provider,
        alpha_project.id,
    )
    # 同 key 新事实必须形成替换链。
    save_memories(
        session,
        [MemoryCandidate("project.database", "semantic", "项目数据库使用 PostgreSQL 16", 5, 1.0, "project")],
        EVAL_USER,
        alpha.id,
        3,
        0.7,
        provider,
        alpha_project.id,
    )
    # 相同 key 在另一个项目中必须能独立存在。
    save_memories(
        session,
        [MemoryCandidate("project.database", "semantic", "项目数据库使用 SQLite", 5, 1.0, "project")],
        EVAL_USER,
        beta.id,
        3,
        0.7,
        provider,
        beta_project.id,
    )
    # 错误候选：低价值和敏感信息都不得落库。
    save_memories(
        session,
        [
            MemoryCandidate("temporary", "semantic", "这一次回答写长一点", 1, 1.0, "global"),
            MemoryCandidate("secret", "profile", "API_KEY=sk-test-12345678901234567890", 5, 1.0, "global"),
        ],
        EVAL_USER,
        alpha.id,
        3,
        0.7,
        provider,
        alpha_project.id,
    )
    return {"alpha": alpha, "beta": beta}


def evaluate() -> dict[str, float]:
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    provider = MockEmbeddingProvider(settings.embedding_dim)
    with SessionLocal() as session:
        _clean(session)
        conversations = _seed(session, provider)
        session.commit()

        hits = 0
        scope_leaks = 0
        for case in cases:
            conversation = conversations[case["conversation"]]
            rows = retrieve_memories(
                session,
                EVAL_USER,
                case["query"],
                3,
                provider,
                conversation_id=conversation.id,
                project_id=conversation.project_id,
            )
            hits += any(case["expect_contains"] in row.content for row in rows)
            allowed = {
                ("global", "global"),
                ("project", conversation.project_id),
                ("conversation", conversation.id),
            }
            scope_leaks += any((row.scope_type, row.scope_key) not in allowed for row in rows)

        active = session.query(Memory).filter(
            Memory.user_id == EVAL_USER,
            Memory.status == "active",
            Memory.is_active.is_(True),
        ).all()
        duplicate_groups = Counter(
            (row.scope_type, row.scope_key, row.content_hash) for row in active
        )
        duplicate_count = sum(max(0, count - 1) for count in duplicate_groups.values())
        false_count = sum(row.normalized_key in {"temporary", "secret"} for row in active)

        old = session.query(Memory).filter(
            Memory.user_id == EVAL_USER,
            Memory.content == "项目数据库使用 SQLite",
            Memory.scope_key == conversations["alpha"].project_id,
        ).one()
        replacement = session.query(Memory).filter(
            Memory.user_id == EVAL_USER,
            Memory.content == "项目数据库使用 PostgreSQL 16",
        ).one()
        conflict_ok = float(old.status == "superseded" and replacement.supersedes_id == old.id)

        context = build_context(
            session,
            "system",
            conversations["alpha"].id,
            "项目数据库是什么",
            2000,
            4,
            EVAL_USER,
            memory_limit=1,
            embedding_provider=provider,
            rag_settings=settings,
            knowledge_intent=False,
        )
        # usage 反馈采用批量 UPDATE；清理当前 Session 的身份缓存后读取数据库实值。
        session.expire_all()
        selected_rows = (
            session.query(Memory).filter(Memory.id.in_(context.memory_ids)).all()
            if context.memory_ids
            else []
        )
        actual_use = float(
            bool(selected_rows) and all(row.usage_count >= 1 for row in selected_rows)
        )
        metrics = {
            "false_memory_rate": false_count / 2,
            "duplicate_rate": duplicate_count / max(1, len(active)),
            "recall_at_3": hits / len(cases),
            "scope_misrecall_rate": scope_leaks / len(cases),
            "conflict_resolution_rate": conflict_ok,
            "context_actual_use_rate": actual_use,
        }
        _clean(session)
        return metrics


def main() -> None:
    init_db()
    metrics = evaluate()
    for name, value in metrics.items():
        print(f"{name}: {value:.3f}")


if __name__ == "__main__":
    main()

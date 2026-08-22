"""SQLite 数据层：SQLAlchemy 2.0 模型与会话管理（P0 阶段）。"""

from datetime import datetime, timezone
from pathlib import Path
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from infrastructure.config import settings


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    """用户工作项目；会话（任务）可以归属到一个项目。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    name: Mapped[str] = mapped_column(String(120))
    workspace_dir: Mapped[str | None] = mapped_column(String(1200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    project_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_message_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatImage(Base):
    """聊天图片附件；原始字节只保存在受控目录，消息中仅保存关联。"""

    __tablename__ = "chat_images"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    message_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    mime_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(
            "uq_agent_runs_running_conversation",
            "conversation_id",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    activity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    execution_mode: Mapped[str] = mapped_column(String(20), default="direct")
    capability_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capability_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed|cancelled
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    execution_mode: Mapped[str] = mapped_column(String(20), default="direct")
    schedule_type: Mapped[str] = mapped_column(String(20))  # once | interval
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    last_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    activity_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planning", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    planner_version: Mapped[str] = mapped_column(String(40), default="p6-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlanStep(Base):
    __tablename__ = "plan_steps"
    __table_args__ = (
        UniqueConstraint("plan_id", "version", "position", name="uq_plan_step_position"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    plan_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    instruction: Mapped[str] = mapped_column(Text)
    tool_hints: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(100), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(100))
    args_summary: Mapped[str] = mapped_column(Text, default="")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20))
    approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_key", name="uq_memories_user_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    kind: Mapped[str] = mapped_column(String(20), default="semantic")  # episodic|semantic|profile
    content: Mapped[str] = mapped_column(Text)
    normalized_key: Mapped[str] = mapped_column(String(200), default="", index=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AssistantSkill(Base):
    """Assistant 对本地 Skill 的启用选择；当前使用 default Assistant。"""

    __tablename__ = "assistant_skills"

    assistant_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    skill_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_documents_user_hash"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    file_type: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(255))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_index"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


def _ensure_sqlite_dir(url: str) -> None:
    """sqlite:///./data/xxx.db 时确保 data 目录存在。"""
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        path = Path(url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.database_url)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    _prepare_sqlite_p6_running_run_index()
    Base.metadata.create_all(engine)
    _migrate_sqlite_p1()
    _migrate_sqlite_p2()
    _migrate_sqlite_p5()
    _migrate_sqlite_p6()
    _migrate_sqlite_p8()
    _migrate_sqlite_p13()


def _migrate_sqlite_p13() -> None:
    """为旧会话补充项目归属字段；旧数据保持为未分组。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if not inspector.has_table("conversations"):
        return
    existing = {column["name"] for column in inspector.get_columns("conversations")}
    with engine.begin() as connection:
        if "project_id" not in existing:
            connection.execute(text("ALTER TABLE conversations ADD COLUMN project_id VARCHAR(32)"))
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_conversations_project_id "
                "ON conversations (project_id)"
            )
        )


def _migrate_sqlite_p8() -> None:
    """为已有 Run 增加本次执行的能力快照，可重复执行。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if not inspector.has_table("agent_runs"):
        return
    existing = {column["name"] for column in inspector.get_columns("agent_runs")}
    additions = {
        "capability_version": "VARCHAR(64)",
        "capability_snapshot": "JSON",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing:
                connection.execute(
                    text(f"ALTER TABLE agent_runs ADD COLUMN {name} {definition}")
                )


def _migrate_sqlite_p6() -> None:
    """为 P5 SQLite 表补齐执行模式字段，可重复执行。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    additions = {
        "agent_runs": ("execution_mode", "VARCHAR(20) NOT NULL DEFAULT 'direct'"),
        "activities": ("execution_mode", "VARCHAR(20) NOT NULL DEFAULT 'direct'"),
    }
    with engine.begin() as connection:
        for table, (name, definition) in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        if inspector.has_table("agent_runs"):
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_agent_runs_running_conversation ON agent_runs (conversation_id) "
                    "WHERE status = 'running'"
                )
            )


def _prepare_sqlite_p6_running_run_index() -> None:
    """旧库建唯一索引前，仅保留每个会话最新的一条 running Run。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if not inspector.has_table("agent_runs"):
        return
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT id, conversation_id FROM agent_runs WHERE status = 'running' "
                "ORDER BY conversation_id, created_at DESC, id DESC"
            )
        ).mappings()
        seen: set[str] = set()
        duplicate_ids: list[str] = []
        for row in rows:
            if row["conversation_id"] in seen:
                duplicate_ids.append(row["id"])
            else:
                seen.add(row["conversation_id"])
        for run_id in duplicate_ids:
            connection.execute(
                text(
                    "UPDATE agent_runs SET status = 'cancelled', "
                    "error = 'P6 migration: duplicate running run', "
                    "completed_at = CURRENT_TIMESTAMP WHERE id = :id"
                ),
                {"id": run_id},
            )


def _migrate_sqlite_p5() -> None:
    """为已有 SQLite agent_runs 表增加 Activity 关联，可重复执行。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if not inspector.has_table("agent_runs"):
        return
    existing = {column["name"] for column in inspector.get_columns("agent_runs")}
    with engine.begin() as connection:
        if "activity_id" not in existing:
            connection.execute(
                text("ALTER TABLE agent_runs ADD COLUMN activity_id VARCHAR(32)")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_agent_runs_activity_id "
                "ON agent_runs (activity_id)"
            )
        )


def _migrate_sqlite_p2() -> None:
    """为已有 P1 SQLite messages 表增加持久化引用字段。"""
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if not inspector.has_table("messages"):
        return
    existing = {column["name"] for column in inspector.get_columns("messages")}
    if "citations" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE messages ADD COLUMN citations JSON"))


def _migrate_sqlite_p1() -> None:
    """为已有 P0 SQLite 数据库补齐 P1 列；新数据库由 create_all 直接创建。"""
    if not settings.database_url.startswith("sqlite"):
        return

    additions = {
        "conversations": {
            "summary": "TEXT",
            "summary_message_count": "INTEGER NOT NULL DEFAULT 0",
            "summary_updated_at": "DATETIME",
        },
        "memories": {
            "normalized_key": "VARCHAR(200) NOT NULL DEFAULT ''",
            "source_conversation_id": "VARCHAR(32)",
            "importance": "INTEGER NOT NULL DEFAULT 3",
            "confidence": "FLOAT NOT NULL DEFAULT 1.0",
            "is_active": "BOOLEAN NOT NULL DEFAULT 1",
            "updated_at": "DATETIME",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in additions.items():
            if not inspector.has_table(table):
                continue
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        connection.execute(
            text("UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL")
        )
        rows = connection.execute(
            text(
                "SELECT id, user_id, normalized_key FROM memories "
                "ORDER BY updated_at DESC, created_at DESC"
            )
        ).mappings()
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row["normalized_key"] or "").strip()
            pair = (row["user_id"], key)
            if not key:
                key = f"legacy.{row['id']}"
            elif pair in seen:
                key = f"duplicate.{row['id']}"
                connection.execute(
                    text(
                        "UPDATE memories SET normalized_key = :key, is_active = 0 "
                        "WHERE id = :id"
                    ),
                    {"key": key, "id": row["id"]},
                )
            if key != (row["normalized_key"] or ""):
                connection.execute(
                    text("UPDATE memories SET normalized_key = :key WHERE id = :id"),
                    {"key": key, "id": row["id"]},
                )
            seen.add((row["user_id"], key))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_user_key "
                "ON memories (user_id, normalized_key)"
            )
        )

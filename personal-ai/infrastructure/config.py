"""全局配置：环境变量 + .env 文件（pydantic-settings）。"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlparse


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Model Gateway ----
    llm_provider: str = "mock"  # mock | openai-compatible
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_timeout_seconds: float = 60.0
    llm_context_window_tokens: int = Field(default=12_096, ge=2_048, le=2_000_000)
    llm_max_output_tokens: int = Field(default=4_096, ge=1, le=262_144)
    # 仅供自动化测试使用；正常运行时模型只来自本地运行时配置库。
    model_environment_fallback_enabled: bool = False

    # ---- Agent Runtime ----
    agent_max_steps: int = 8
    agent_timeout_seconds: float = 180.0

    # ---- Tools / Approval ----
    tools_enabled: bool = True
    tool_timeout_seconds: float = 30.0
    approval_timeout_seconds: float = 60.0
    sandbox_dir: str = "./data/sandbox"
    skills_dir: str = "./skills"
    skill_trash_dir: str = "./data/skill-trash"
    plugins_dir: str = "./plugins"
    plugin_trash_dir: str = "./data/plugin-trash"
    artifacts_dir: str = "./data/artifacts"
    artifact_max_bytes: int = 52_428_800
    artifact_public_base_url: str = "http://localhost:8787"
    coding_workspace_dir: str = "./data/coding-workspace"
    coding_check_timeout_seconds: float = 120.0

    # ---- MCP ----
    mcp_enabled: bool = True
    mcp_config_file: str = "./config/mcp_servers.yaml"

    # ---- Activity Worker ----
    activity_enabled: bool = True
    activity_poll_seconds: int = Field(default=5, ge=1, le=60)

    # ---- Planner ----
    planner_enabled: bool = True
    planner_max_steps: int = Field(default=6, ge=2, le=10)
    planner_max_replans: int = Field(default=1, ge=0, le=2)
    planner_step_max_turns: int = Field(default=3, ge=1, le=5)
    planner_max_tool_calls: int = Field(default=12, ge=1, le=30)
    planner_observation_tokens_budget: int = Field(default=1200, ge=200, le=3000)

    # ---- Context Engine ----
    # 兼容没有模型能力配置的内部调用；实际聊天按所选模型窗口动态计算。
    context_max_tokens: int = 8000
    context_recent_messages: int = 40
    memory_tokens_budget: int = 600
    rag_tokens_budget: int = 800
    summary_tokens_budget: int = 800

    # ---- Memory / Summary ----
    memory_enabled: bool = True
    memory_recall_limit: int = 5
    memory_min_importance: int = 3
    memory_min_confidence: float = 0.7
    summary_trigger_messages: int = 12
    summary_keep_recent_messages: int = 6

    # ---- RAG / Chunking ----
    rag_enabled: bool = True
    rag_query_gate_enabled: bool = True
    rag_vector_top_k: int = 12
    rag_bm25_top_k: int = 12
    rag_final_top_k: int = 5
    rag_rrf_k: int = 60
    rag_min_vector_similarity: float = 0.30
    rag_chunk_target_chars: int = 450
    rag_chunk_max_chars: int = 700
    rag_chunk_max_tokens: int = 420
    rag_chunk_overlap_sentences: int = 1

    # ---- Files ----
    file_storage_dir: str = "./data/uploads"
    file_max_bytes: int = 10_485_760
    file_allowed_extensions: str = ".pdf,.docx,.txt,.md"
    file_max_pages: int = 300
    file_max_parsed_chars: int = 2_000_000
    file_max_chunks: int = 5_000
    docx_max_uncompressed_bytes: int = 52_428_800
    index_timeout_seconds: float = 180.0
    pdf_needs_ocr_min_chars: int = 100
    pdf_needs_ocr_min_text_page_ratio: float = 0.2

    # ---- Chat Images ----
    chat_image_storage_dir: str = "./data/chat-images"
    chat_image_max_bytes: int = 10_485_760
    chat_image_max_count: int = Field(default=4, ge=1, le=10)
    chat_image_max_pixels: int = Field(default=16_777_216, ge=65_536, le=100_000_000)
    chat_image_recent_turns: int = Field(default=2, ge=0, le=10)

    # ---- Embedding ----
    embedding_provider: str = "local"  # local | openai-compatible | mock
    embedding_model_path: str = (
        "C:/Users/twb/.cache/modelscope/models/BAAI--bge-small-zh-v1.5/snapshots/master"
    )
    embedding_dim: int = 512
    embedding_batch_size: int = 32
    embedding_query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""

    # ---- Database ----
    database_url: str = (
        "postgresql+psycopg://personal_ai:personal_ai_local@localhost:5432/personal_ai"
    )

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8787
    cors_origins: str = "http://localhost:4321"

    # ---- Character / Prompts ----
    character_file: str = "core/chat/character.yaml"
    system_prompt_file: str = "prompts/system/main.md"
    rag_context_prompt_file: str = "prompts/rag/context.md"
    runtime_settings_file: str = "./data/runtime-settings.json"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def file_allowed_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.file_allowed_extensions.split(",") if item.strip()}

    @property
    def environment_model_declared(self) -> bool:
        """是否显式通过环境变量或 .env 声明了模型，而非使用类默认值。"""
        if self.model_environment_fallback_enabled:
            return False
        return bool(
            {"llm_provider", "llm_base_url", "llm_api_key", "llm_model"}
            & self.model_fields_set
        )

    @property
    def environment_model_error(self) -> str | None:
        if not self.environment_model_declared:
            return None
        if self.llm_provider != "openai-compatible":
            return "环境模型的 LLM_PROVIDER 必须是 openai-compatible"
        parsed = urlparse(self.llm_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "环境模型缺少有效的 LLM_BASE_URL"
        if not self.llm_model.strip():
            return "环境模型缺少 LLM_MODEL"
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if not is_local and not self.llm_api_key.strip():
            return "云端环境模型缺少 LLM_API_KEY"
        return None

    @property
    def environment_model_configured(self) -> bool:
        return self.environment_model_declared and self.environment_model_error is None


settings = Settings()

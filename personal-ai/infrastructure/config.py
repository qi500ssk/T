"""全局配置：环境变量 + .env 文件（pydantic-settings）。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ---- Agent Runtime ----
    agent_max_steps: int = 10
    agent_timeout_seconds: float = 120.0
    agent_max_retries: int = 2

    # ---- Context Engine ----
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
    database_url: str = "sqlite:///./data/personal_ai.db"

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8787
    cors_origins: str = "http://localhost:4321"

    # ---- Character / Prompts ----
    character_file: str = "core/character.yaml"
    system_prompt_file: str = "prompts/system/main.md"
    rag_context_prompt_file: str = "prompts/rag/context.md"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def file_allowed_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.file_allowed_extensions.split(",") if item.strip()}


settings = Settings()

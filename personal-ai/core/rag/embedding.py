"""RAG 域 Embedding Gateway：本地 BGE、OpenAI-compatible 与 Mock。"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import logging
from pathlib import Path

import httpx
from infrastructure.paths import data_path


LOCAL_MODELS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {"name": "多语言 MiniLM · 本地推荐", "dimension": 384, "size": "约 220 MB", "language": "中文 / 多语言"},
    "sentence-transformers/all-MiniLM-L6-v2": {"name": "MiniLM L6 · 英文", "dimension": 384, "size": "约 90 MB", "language": "英文"},
    "BAAI/bge-small-zh-v1.5": {"name": "BGE Small · 中文备用", "dimension": 512, "size": "约 90 MB", "language": "中文"},
}
DEFAULT_LOCAL_MODEL = next(iter(LOCAL_MODELS))


class KeywordEmbeddingProvider:
    """无向量的真实关键词模式，不生成伪语义向量。"""
    model_name = "keyword-v1"
    dimension = 0

    def __init__(self, reason=""):
        self.reason = reason

    def count_tokens(self, text):
        return max(1, len(text))

    def embed_documents(self, texts):
        return [[] for _ in texts]

    def embed_query(self, text):
        return []

    def close(self):
        pass


class FastEmbeddingProvider:
    def __init__(self, model, *, download=False):
        if model not in LOCAL_MODELS:
            raise ValueError("请选择已支持的本地检索模型")
        from fastembed import TextEmbedding
        self.model_name = "fastembed-mean-v1:" + model
        self.dimension = LOCAL_MODELS[model]["dimension"]
        self.reason = ""
        self._lock = threading.Lock()
        self._model = TextEmbedding(model_name=model, cache_dir=data_path("embedding-models"),
                                    local_files_only=not download, threads=2)
        from tokenizers import Tokenizer
        original = self._model.model.tokenizer
        self._tokenizer = Tokenizer.from_str(original.to_str())
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self.max_tokens = (original.truncation or {}).get("max_length", 256)
        self.min_similarity = 0.2 if "multilingual-MiniLM" in model else 0.3

    def count_tokens(self, text):
        return len(self._tokenizer.encode(text).ids)

    def _pieces(self, text):
        offsets = [pair for pair in self._tokenizer.encode(text).offsets if pair[1] > pair[0]]
        step = max(8, self.max_tokens - 16)
        return [text[offsets[start][0]:offsets[min(start + step, len(offsets)) - 1][1]]
                for start in range(0, len(offsets), step)] or [text]

    def _embed(self, texts, query=False):
        # 已有片段可能超过新模型长度：分窗后平均，不静默截掉尾部，也不改变来源 chunk ID。
        pieces = [self._pieces(text) for text in texts]
        flattened = [piece for group in pieces for piece in group]
        method = self._model.query_embed if query else self._model.passage_embed
        with self._lock:
            vectors = [row.tolist() for row in method(flattened, batch_size=16)]
        result, position = [], 0
        for group in pieces:
            selected = vectors[position:position + len(group)]
            result.append(_normalize([sum(values) / len(selected) for values in zip(*selected)]))
            position += len(group)
        return _check_dimensions(result, self.dimension)

    def embed_documents(self, texts):
        return self._embed(texts) if texts else []

    def embed_query(self, text):
        return self._embed([text], query=True)[0]

    def close(self):
        self._model = None


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _check_dimensions(vectors: list[list[float]], expected: int) -> list[list[float]]:
    if any(len(vector) != expected for vector in vectors):
        actual = sorted({len(vector) for vector in vectors})
        raise ValueError(f"Embedding 维度不匹配：期望 {expected}，实际 {actual}")
    if any(not math.isfinite(v) for row in vectors for v in row):
        raise ValueError("Embedding 返回了无效数值")
    return vectors


class LocalEmbeddingProvider:
    def __init__(self, model_path: str, dimension: int, batch_size: int, query_instruction: str):
        self.model_path = Path(model_path)
        self.dimension = dimension
        self.batch_size = batch_size
        self.query_instruction = query_instruction
        self.model_name = str(self.model_path)
        self._model = None
        self._load_lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is None:
                if not (self.model_path / "config.json").is_file():
                    raise FileNotFoundError(f"Embedding 模型路径无效：{self.model_path}")
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(str(self.model_path), local_files_only=True,
                    trust_remote_code=False, model_kwargs={"use_safetensors": True})
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        return _check_dimensions(vectors, self.dimension)

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([self.query_instruction + text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self._load().tokenizer.encode(text, add_special_tokens=False))

    def close(self) -> None:
        self._model = None


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        query_instruction: str,
        request_dimensions: bool = False,
    ):
        if not base_url or not api_key or not model:
            raise ValueError("OpenAI-compatible Embedding 需要 BASE_URL、API_KEY 和 MODEL")
        self.model_name = model
        self.dimension = dimension
        self.query_instruction = query_instruction
        self.request_dimensions = request_dimensions
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model_name, "input": texts, "encoding_format": "float"}
        if self.request_dimensions:
            payload["dimensions"] = self.dimension
        response = self._client.post("/embeddings", json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"Embedding API 返回 HTTP {response.status_code}，请检查服务和配置")
        items = sorted(response.json().get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [_normalize([float(value) for value in item["embedding"]]) for item in items]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding API 返回数量不匹配")
        return _check_dimensions(vectors, self.dimension)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self.query_instruction + text])[0]

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)

    def close(self) -> None:
        self._client.close()


class MockEmbeddingProvider:
    """稳定的词项哈希向量，供离线测试与无模型联调。"""

    def __init__(self, dimension: int = 512):
        self.dimension = dimension
        self.model_name = "mock-hash-embedding"

    @staticmethod
    def _terms(text: str) -> list[str]:
        lowered = text.lower()
        terms = re.findall(r"[a-z0-9_]+", lowered)
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        terms.extend(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
        return terms or [lowered]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for term in self._terms(text):
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self.dimension
            vector[index] += 1.0
        return _normalize(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)

    def close(self) -> None:
        pass


# 本地模型的标准存放位置：项目数据目录、ModelScope 与 HuggingFace 缓存。
_LOCAL_MODEL_CANDIDATES = (
    Path("data/models/bge-small-zh-v1.5"),
    Path.home() / ".cache/modelscope/models/BAAI--bge-small-zh-v1.5/snapshots/master",
    Path.home() / ".cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/snapshots",
)


def resolve_local_model_path(configured: str) -> str:
    """配置为空时按标准位置查找模型，避免把某台机器的绝对路径写进源码。"""
    if configured:
        return configured
    for candidate in _LOCAL_MODEL_CANDIDATES:
        if (candidate / "config.json").is_file():
            return str(candidate)
        if candidate.is_dir():
            for child in sorted(candidate.iterdir()):
                if (child / "config.json").is_file():
                    return str(child)
    raise FileNotFoundError(
        "未找到本地 Embedding 模型。请把模型下载到 ./data/models/bge-small-zh-v1.5，"
        "或在 .env 设置 EMBEDDING_MODEL_PATH；也可以改用 EMBEDDING_PROVIDER=openai-compatible。"
    )


def build_embedding_provider(settings, *, download=False, strict=False):
    if settings.embedding_provider == "keyword":
        return KeywordEmbeddingProvider()
    if settings.embedding_provider == "fastembed":
        try:
            return FastEmbeddingProvider(settings.embedding_model or DEFAULT_LOCAL_MODEL, download=download)
        except Exception:
            if strict or download:
                raise
            return KeywordEmbeddingProvider("本地模型尚未就绪，可在设置中下载；当前使用关键词检索")
    if settings.embedding_provider == "local":
        try:
            import importlib.util
            if importlib.util.find_spec("sentence_transformers") is None:
                raise ImportError("旧版模型运行依赖未安装")
            return LocalEmbeddingProvider(
                resolve_local_model_path(settings.embedding_model_path),
                settings.embedding_dim,
                getattr(settings, "embedding_batch_size", 32),
                settings.embedding_query_instruction,
            )
        except (FileNotFoundError, ImportError):
            if strict:
                raise
            return KeywordEmbeddingProvider("旧版本地模型未就绪，请在设置中选择轻量检索模型；当前使用关键词检索")
    if settings.embedding_provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(
            settings.embedding_base_url,
            settings.embedding_api_key,
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_query_instruction,
            request_dimensions=getattr(settings, "embedding_request_dimensions", False),
        )
    if settings.embedding_provider == "mock":
        return MockEmbeddingProvider(settings.embedding_dim)
    raise ValueError(f"不支持的 EMBEDDING_PROVIDER：{settings.embedding_provider}")

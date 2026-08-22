"""RAG 域 Embedding Gateway：本地 BGE、OpenAI-compatible 与 Mock。"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from pathlib import Path

import httpx


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _check_dimensions(vectors: list[list[float]], expected: int) -> list[list[float]]:
    if any(len(vector) != expected for vector in vectors):
        actual = sorted({len(vector) for vector in vectors})
        raise ValueError(f"Embedding 维度不匹配：期望 {expected}，实际 {actual}")
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

                self._model = SentenceTransformer(str(self.model_path), local_files_only=True)
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
        pass


class OpenAICompatibleEmbeddingProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dimension: int,
        query_instruction: str,
    ):
        if not base_url or not api_key or not model:
            raise ValueError("OpenAI-compatible Embedding 需要 BASE_URL、API_KEY 和 MODEL")
        self.model_name = model
        self.dimension = dimension
        self.query_instruction = query_instruction
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60,
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post("/embeddings", json={"model": self.model_name, "input": texts})
        if response.status_code != 200:
            raise RuntimeError(f"Embedding API 错误 {response.status_code}: {response.text[:300]}")
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


def build_embedding_provider(settings):
    if settings.embedding_provider == "local":
        return LocalEmbeddingProvider(
            settings.embedding_model_path,
            settings.embedding_dim,
            settings.embedding_batch_size,
            settings.embedding_query_instruction,
        )
    if settings.embedding_provider == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(
            settings.embedding_base_url,
            settings.embedding_api_key,
            settings.embedding_model,
            settings.embedding_dim,
            settings.embedding_query_instruction,
        )
    if settings.embedding_provider == "mock":
        return MockEmbeddingProvider(settings.embedding_dim)
    raise ValueError(f"不支持的 EMBEDDING_PROVIDER：{settings.embedding_provider}")

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
WORD_RE = re.compile(r"[a-z0-9_]+")


class Embedder(Protocol):
    name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _tokens(text: str) -> list[str]:
    text = text.lower()
    tokens: list[str] = []
    for run in CJK_RUN_RE.findall(text):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    tokens.extend(WORD_RE.findall(text))
    return tokens


class HashingEmbedder:
    """Deterministic lexical hashing embedder for offline development.

    This is NOT BGE-M3 and must not be used in thesis experiments. It exists so
    the ingestion/retrieval pipeline can run without downloading a 2 GB model.
    Swap it with BGEM3Embedder via EMBEDDING_MODEL.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension
        self.name = f"hashing-dev-{dimension}"

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        counts: dict[str, int] = {}
        for token in _tokens(text):
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class BGEM3Embedder:
    """Adapter for BAAI/bge-m3.

    Requires `pip install FlagEmbedding` and a model download. Kept out of the
    default dependency set so the skeleton remains runnable offline.
    """

    name = "BAAI/bge-m3"

    def __init__(self, dimension: int = 1024, device: str | None = None) -> None:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]

        self.dimension = dimension
        self._model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True, device=device)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        result = self._model.encode(texts, batch_size=8, max_length=1024)
        return [list(map(float, row)) for row in result["dense_vecs"]]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def build_embedder(model_name: str, dimension: int = 1024) -> Embedder:
    if model_name.startswith("hashing"):
        return HashingEmbedder(dimension=dimension)
    if model_name in {"BAAI/bge-m3", "bge-m3"}:
        return BGEM3Embedder(dimension=dimension)
    raise ValueError(f"Unknown embedding model: {model_name}")


@lru_cache(maxsize=2)
def get_embedder(model_name: str, dimension: int = 1024) -> Embedder:
    return build_embedder(model_name, dimension)

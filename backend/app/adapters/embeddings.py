"""Text embeddings for RAG (pgvector, cosine distance)."""

from __future__ import annotations

import hashlib
import math
import re
from itertools import pairwise
from typing import Literal, Protocol

from openai import AsyncOpenAI, OpenAIError

from app.core.config import EMBEDDING_DIMENSIONS
from app.core.errors import UpstreamError


class Embedder(Protocol):
    provider: str
    mode: Literal["live", "demo"]
    dimensions: int
    # Identifies the vector space: stored with every embedded chunk, and retrieval only
    # compares vectors that share it (vectors from different embedders are meaningless together).
    model_id: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    provider = "openai"
    mode: Literal["live", "demo"] = "live"
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, client: AsyncOpenAI, *, model: str, batch_size: int = 128) -> None:
        self._client = client
        self._model = model
        self._batch_size = batch_size
        self.model_id = f"openai:{model}:{self.dimensions}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            try:
                response = await self._client.embeddings.create(
                    model=self._model, input=batch, dimensions=self.dimensions
                )
            except OpenAIError as exc:
                raise UpstreamError("Embedding request failed") from exc
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors


_TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


class HashingEmbedder:
    """Deterministic lexical embeddings (feature hashing of unigrams + bigrams).

    Not semantic, but stable across runs and good enough for keyword-level retrieval in
    demo mode and tests. Vectors are L2-normalised so cosine distance behaves.
    """

    provider = "adapt-hashing"
    mode: Literal["live", "demo"] = "demo"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.model_id = f"adapt-hashing:v1:{dimensions}"

    def _vector(self, text: str) -> list[float]:
        tokens = [t.lower() for t in _TOKEN.findall(text)]
        features = tokens + [f"{a} {b}" for a, b in pairwise(tokens)]
        vec = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

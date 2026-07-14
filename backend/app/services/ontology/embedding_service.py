import hashlib
import json
import math
import os
import struct
from functools import lru_cache


def _hash_embedding(text: str, dim: int = 128) -> list[float]:
    """Deterministic fallback embedding when no API embeddings are configured."""
    vec = [0.0] * dim
    tokens = (text or "").lower().split()
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=5000)
def compute_embedding(text: str) -> tuple[float, ...]:
    text = (text or "").strip()
    if not text:
        return tuple([0.0] * 128)

    openai_key = os.getenv("OPENAI_API_KEY")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    if openai_key or azure_key:
        try:
            from langchain_openai import OpenAIEmbeddings

            model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            emb = OpenAIEmbeddings(api_key=openai_key or azure_key, model=model)
            vector = emb.embed_query(text)
            return tuple(float(x) for x in vector)
        except Exception:
            pass

    return tuple(_hash_embedding(text))


def compute_embeddings_batch(texts: list[str]) -> list[list[float]]:
    return [list(compute_embedding(t)) for t in texts]


def cosine_similarity(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embedding_to_blob(vector: list[float] | tuple[float, ...]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def blob_to_embedding(blob: bytes) -> list[float]:
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def embed_ontology_kpis(db) -> int:
    """Compute and persist embeddings for all active ontology KPIs."""
    from app.models.ontology import OntologyKPI

    rows = db.query(OntologyKPI).filter(OntologyKPI.status == "active").all()
    count = 0
    for row in rows:
        aliases = []
        try:
            aliases = json.loads(row.aliases) if row.aliases else []
        except Exception:
            pass
        text = f"{row.name} {row.definition} {' '.join(aliases)}"
        vector = compute_embedding(text)
        row.embedding = embedding_to_blob(vector)
        count += 1
    db.commit()
    return count

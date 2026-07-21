import hashlib
import json
import math
import os
import struct
from collections import OrderedDict

import logging as _emb_logging

_emb_logger = _emb_logging.getLogger(__name__)


def _hash_embedding(text: str, dim: int = 1536) -> list[float]:
    """Deterministic fallback embedding when no API embeddings are configured.

    WARNING: These are NOT semantic vectors. Two synonyms will produce
    completely different vectors. Similarity scores from hash embeddings
    must NEVER be used for auto-approval decisions.
    """
    vec = [0.0] * dim
    tokens = (text or "").lower().split()
    for token in tokens:
        h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# LRU Embedding Cache — bounded to prevent OOM at scale
# At 1536 floats × 8 bytes ≈ 12KB per entry, 10K entries ≈ 120MB
# ---------------------------------------------------------------------------
_EMBEDDING_CACHE_MAXSIZE = int(os.getenv("EMBEDDING_CACHE_MAXSIZE", "10000"))


class _LRUEmbeddingCache:
    """Thread-safe-ish bounded LRU cache backed by OrderedDict."""

    def __init__(self, maxsize: int = 10000):
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def get(self, key: str) -> tuple[float, ...] | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value: tuple[float, ...]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = value
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)  # evict oldest
            self._cache[key] = value

    def clear(self) -> int:
        count = len(self._cache)
        self._cache.clear()
        return count

    def __len__(self) -> int:
        return len(self._cache)


_embedding_cache = _LRUEmbeddingCache(maxsize=_EMBEDDING_CACHE_MAXSIZE)


def clear_embedding_cache() -> int:
    """Clear the in-memory embedding cache. Returns count of cleared entries."""
    return _embedding_cache.clear()


# ---------------------------------------------------------------------------
# Embedding fallback tracking
# ---------------------------------------------------------------------------
_embedding_consecutive_failures = 0
_EMBEDDING_MAX_FAILURES = 3
_using_hash_fallback = False


def reset_embedding_failures() -> None:
    """Reset the failure counter — call at the start of each extraction run."""
    global _embedding_consecutive_failures, _using_hash_fallback
    _embedding_consecutive_failures = 0
    _using_hash_fallback = False


def is_using_hash_fallback() -> bool:
    """Return True if embeddings are currently using the hash fallback.

    Callers (ontology_service) MUST check this to prevent auto-approving
    matches based on non-semantic hash vectors.
    """
    return _using_hash_fallback


def get_active_embedding_model() -> str:
    """Return the name of the currently active embedding model."""
    if _using_hash_fallback:
        return "hash_fallback"
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    if azure_key:
        return os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    return "hash_fallback"


def compute_embedding(text: str) -> tuple[float, ...]:
    global _embedding_consecutive_failures, _using_hash_fallback
    text = (text or "").strip()
    if not text:
        return tuple([0.0] * 1536)

    cached = _embedding_cache.get(text)
    if cached is not None:
        return cached

    openai_key = os.getenv("OPENAI_API_KEY")
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if (openai_key or azure_key) and _embedding_consecutive_failures < _EMBEDDING_MAX_FAILURES:
        try:
            if azure_key and azure_endpoint:
                from langchain_openai import AzureOpenAIEmbeddings
                deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
                api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
                emb = AzureOpenAIEmbeddings(
                    api_key=azure_key,
                    azure_endpoint=azure_endpoint,
                    azure_deployment=deployment,
                    api_version=api_version
                )
            else:
                from langchain_openai import OpenAIEmbeddings
                model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
                emb = OpenAIEmbeddings(api_key=openai_key, model=model)
            
            vector = emb.embed_query(text)
            result = tuple(float(x) for x in vector)
            _embedding_cache.put(text, result)
            _embedding_consecutive_failures = 0  # reset on success
            _using_hash_fallback = False
            return result
        except Exception as e:
            _embedding_consecutive_failures += 1
            _emb_logger.warning(
                "Embedding API failure #%d/%d: %s",
                _embedding_consecutive_failures, _EMBEDDING_MAX_FAILURES, e,
            )

    if _embedding_consecutive_failures >= _EMBEDDING_MAX_FAILURES:
        _using_hash_fallback = True
        _emb_logger.warning(
            "Embedding API disabled after %d consecutive failures. "
            "Using hash fallback (dim=1536). Hash fallback scores CANNOT be auto-approved.",
            _embedding_consecutive_failures,
        )
    else:
        _using_hash_fallback = True

    result = tuple(_hash_embedding(text))
    _embedding_cache.put(text, result)
    return result


def compute_embeddings_batch(texts: list[str]) -> list[list[float]]:
    global _embedding_consecutive_failures, _using_hash_fallback
    cleaned_texts = [(t or "").strip() for t in texts]
    needed_texts = list(set([t for t in cleaned_texts if t and t not in _embedding_cache]))
    
    if needed_texts and _embedding_consecutive_failures < _EMBEDDING_MAX_FAILURES:
        openai_key = os.getenv("OPENAI_API_KEY")
        azure_key = os.getenv("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        if openai_key or azure_key:
            try:
                if azure_key and azure_endpoint:
                    from langchain_openai import AzureOpenAIEmbeddings
                    deployment = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small"
                    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
                    emb = AzureOpenAIEmbeddings(
                        api_key=azure_key,
                        azure_endpoint=azure_endpoint,
                        azure_deployment=deployment,
                        api_version=api_version
                    )
                else:
                    from langchain_openai import OpenAIEmbeddings
                    model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
                    emb = OpenAIEmbeddings(api_key=openai_key, model=model)
                
                vectors = emb.embed_documents(needed_texts)
                for t, vec in zip(needed_texts, vectors):
                    _embedding_cache.put(t, tuple(float(x) for x in vec))
                _embedding_consecutive_failures = 0
                _using_hash_fallback = False
            except Exception as e:
                _embedding_consecutive_failures += 1
                _using_hash_fallback = True
                _emb_logger.warning(
                    "Embedding API batch failure #%d/%d: %s. Falling back to individual embedding calls.",
                    _embedding_consecutive_failures, _EMBEDDING_MAX_FAILURES, e,
                )
                for t in needed_texts:
                    compute_embedding(t)
        else:
            _using_hash_fallback = True
            for t in needed_texts:
                compute_embedding(t)
    else:
        for t in needed_texts:
            compute_embedding(t)

    results = []
    for t in cleaned_texts:
        if not t:
            results.append([0.0] * 1536)
        else:
            cached = _embedding_cache.get(t)
            results.append(list(cached) if cached else [0.0] * 1536)
    return results


def cosine_similarity(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    if not a or not b or len(a) != len(b):
        if a and b and len(a) != len(b):
            _emb_logger.warning(
                "Embedding dimension mismatch: %d vs %d. Returning 0.0.",
                len(a), len(b),
            )
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


def embed_ontology_kpis(db, force: bool = False) -> int:
    """Compute and persist embeddings for active ontology KPIs.
    
    If force is False, skips rows that already have non-null embeddings to save API calls.

    Also invalidates the ontology match cache (Fix #5) since the bank has
    changed and cached match results may be stale.
    """
    from app.models.ontology import OntologyKPI
    from app.services.ontology.ontology_cache import invalidate_ontology_cache

    model_name = get_active_embedding_model()

    q = db.query(OntologyKPI).filter(OntologyKPI.status == "active")
    if not force:
        q = q.filter(OntologyKPI.embedding.is_(None))
    rows = q.all()
    
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
        # Track which model generated this embedding
        if hasattr(row, "embedding_model"):
            row.embedding_model = model_name
        count += 1
        
    if count:
        db.commit()

    # Fix #5: Invalidate stale cache entries now that the bank has changed
    try:
        invalidate_ontology_cache(db)
    except Exception:
        pass

    return count

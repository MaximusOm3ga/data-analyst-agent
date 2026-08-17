import hashlib
import os
from typing import List, Optional

import httpx
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
    _LOCAL_AVAILABLE = True
    _LOCAL_MODEL_NAME = os.getenv("TRIAGE_EMBEDDINGS_LOCAL_MODEL", "all-MiniLM-L6-v2")
    _LOCAL_MODEL = None
except Exception:
    _LOCAL_AVAILABLE = False
    _LOCAL_MODEL = None
    _LOCAL_MODEL_NAME = None


MOCK_EMBEDDING_DIMENSION = 32
_CACHED_DIMENSION: Optional[int] = None


def _embed_text_mock(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec.tolist()
    return (vec / norm).tolist()


def _get_embeddings_mode() -> str:
    mode = os.getenv("TRIAGE_EMBEDDINGS_MODE", "auto").strip().lower()
    if mode not in {"auto", "api", "mock"}:
        return "auto"
    return mode


def _get_embeddings_api_key() -> str:
    return (
        os.getenv("TRIAGE_EMBEDDINGS_API_KEY", "").strip()
        or os.getenv("TRIAGE_LLM_API_KEY", "").strip()
    )


def _should_use_api() -> bool:
    mode = _get_embeddings_mode()
    if mode == "mock":
        return False
    key = _get_embeddings_api_key()
    if mode == "api":
        if not key:
            raise RuntimeError("TRIAGE_EMBEDDINGS_API_KEY (or TRIAGE_LLM_API_KEY) is required in api mode.")
        return True
    return bool(key)


def _embed_text_api(text: str) -> List[float]:
    api_key = _get_embeddings_api_key()
    if not api_key:
        raise RuntimeError("Missing embeddings API key.")
    base_url = os.getenv("TRIAGE_EMBEDDINGS_BASE_URL", "").strip() or os.getenv(
        "TRIAGE_LLM_BASE_URL", "https://api.groq.com/openai/v1"
    )
    model = os.getenv("TRIAGE_EMBEDDINGS_MODEL", "text-embedding-3-small")
    timeout_s = float(os.getenv("TRIAGE_EMBEDDINGS_TIMEOUT_SECONDS", "45"))
    dimensions_raw = os.getenv("TRIAGE_EMBEDDINGS_DIMENSIONS", "").strip()

    payload = {"model": model, "input": text}
    if dimensions_raw:
        try:
            payload["dimensions"] = int(dimensions_raw)
        except ValueError:
            pass

    endpoint = f"{base_url.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(endpoint, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        vector = data["data"][0]["embedding"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected embeddings response format: {data}") from exc
    if not isinstance(vector, list) or not vector:
        raise RuntimeError("Embeddings response did not contain a non-empty vector.")
    return [float(v) for v in vector]


def _get_local_model():
    global _LOCAL_MODEL
    if not _LOCAL_AVAILABLE:
        raise RuntimeError("Local sentence-transformers model not available")
    if _LOCAL_MODEL is None:
        # load and cache model (may take a moment on first call)
        _LOCAL_MODEL = SentenceTransformer(_LOCAL_MODEL_NAME)
    return _LOCAL_MODEL


def _embed_text_local(text: str) -> List[float]:
    model = _get_local_model()
    # sentence-transformers returns numpy array; ensure list[float]
    vec = model.encode(text, normalize_embeddings=True)
    if hasattr(vec, "tolist"):
        return [float(x) for x in vec.tolist()]
    return [float(x) for x in list(vec)]


def embed_text(text: str) -> List[float]:
    """Choose embedding source by mode:
    - mock: deterministic local mock
    - api: call external API (requires key)
    - local: use sentence-transformers local model
    - auto: prefer API if key present, else local if available, else mock
    """
    mode = _get_embeddings_mode()
    if mode == "mock":
        return _embed_text_mock(text)
    if mode == "api":
        return _embed_text_api(text)
    if mode == "local":
        try:
            return _embed_text_local(text)
        except Exception:
            return _embed_text_mock(text)

    if _should_use_api():
        try:
            return _embed_text_api(text)
        except Exception:
            if _LOCAL_AVAILABLE:
                try:
                    return _embed_text_local(text)
                except Exception:
                    return _embed_text_mock(text)
            return _embed_text_mock(text)

    if _LOCAL_AVAILABLE:
        try:
            return _embed_text_local(text)
        except Exception:
            return _embed_text_mock(text)
    return _embed_text_mock(text)


def get_embedding_dimension() -> int:
    global _CACHED_DIMENSION
    if _CACHED_DIMENSION is not None:
        return _CACHED_DIMENSION

    configured = os.getenv("KB_EMBEDDING_DIMENSION", "").strip()
    if configured:
        _CACHED_DIMENSION = int(configured)
        return _CACHED_DIMENSION

    _CACHED_DIMENSION = len(embed_text("dimension_probe"))
    return _CACHED_DIMENSION


def vector_to_pg_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


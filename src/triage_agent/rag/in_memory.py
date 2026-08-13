import hashlib
from typing import List, Dict, Any
import numpy as np
from .base import VectorStore


def _embed_text_deterministic(text: str) -> np.ndarray:
    # Create a deterministic fixed-size vector from sha256 digest
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    # normalize
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec
    return vec / norm


class InMemoryVectorStore(VectorStore):
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []
        self._next_id = 1

    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        for doc in documents:
            text = doc.get("text", "")
            vec = _embed_text_deterministic(text)
            entry = {
                "id": doc.get("id") or f"doc-{self._next_id}",
                "text": text,
                "metadata": doc.get("metadata", {}),
                "vector": vec,
            }
            self._next_id += 1
            self._docs.append(entry)

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if not self._docs:
            return []
        qv = _embed_text_deterministic(query)
        scored = []
        for d in self._docs:
            vec = d["vector"]
            score = float(np.dot(qv, vec))
            scored.append((score, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, d in scored[:k]:
            results.append({"id": d["id"], "text": d["text"], "metadata": d["metadata"], "score": score})
        return results

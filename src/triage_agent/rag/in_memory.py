from typing import List, Dict, Any
import numpy as np
from .base import VectorStore
from .embeddings import embed_text_deterministic


class InMemoryVectorStore(VectorStore):
    def __init__(self):
        self._docs: List[Dict[str, Any]] = []
        self._next_id = 1

    def initialize(self) -> None:
        return None

    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        for doc in documents:
            text = doc.get("text", "")
            vec = np.array(embed_text_deterministic(text), dtype=np.float32)
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
        qv = np.array(embed_text_deterministic(query), dtype=np.float32)
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

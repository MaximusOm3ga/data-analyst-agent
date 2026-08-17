import hashlib
from typing import List

import numpy as np


EMBEDDING_DIMENSION = 32


def embed_text_deterministic(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm == 0:
        return vec.tolist()
    return (vec / norm).tolist()


def vector_to_pg_literal(vector: List[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"

from typing import List, Dict, Any
from ..rag.store import default_vector_store
from ..rag.ingest import ingest_documents
from ..schemas import KnowledgeBaseDocument, KnowledgeBaseSearchResult


def initialize_kb_store() -> Dict[str, Any]:
    default_vector_store.initialize()
    return {"status": "initialized"}


def ingest_kb_documents(documents: List[KnowledgeBaseDocument]) -> Dict[str, Any]:
    payload = []
    for doc in documents:
        payload.append({
            "id": doc.id,
            "text": doc.content,
            "metadata": {
                "title": doc.title,
                "source_url": doc.source_url,
                "category": doc.category,
                **doc.metadata,
            },
        })
    return ingest_documents(default_vector_store, payload)


def search_kb(query: str, limit: int = 5) -> List[KnowledgeBaseSearchResult]:
    results = default_vector_store.retrieve(query, k=limit)
    return [
        KnowledgeBaseSearchResult(
            id=r["id"],
            text=r["text"],
            score=float(r.get("score", 0.0)),
            metadata=r.get("metadata", {}),
        )
        for r in results
    ]

from typing import List, Dict


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    # naive whitespace chunker that respects word boundaries
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap
    return chunks


def ingest_documents(vector_store, docs: List[Dict[str, str]]):
    # Each doc: {"id":..., "text":..., "metadata": {...}}
    to_add = []
    for d in docs:
        chunks = chunk_text(d.get("text", ""), chunk_size=200, overlap=40)
        for i, c in enumerate(chunks):
            to_add.append({
                "id": f"{d.get('id')}-chunk-{i}",
                "text": c,
                "metadata": {**d.get("metadata", {}), "source_id": d.get("id"), "chunk_index": i},
            })
    vector_store.add_documents(to_add)
    return {"ingested_chunks": len(to_add), "documents": len(docs)}

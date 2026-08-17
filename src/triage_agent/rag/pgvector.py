import json
from typing import List, Dict, Any
from .base import VectorStore
from .embeddings import embed_text, get_embedding_dimension, vector_to_pg_literal

# pgvector adapter using psycopg (v3) with OpenAI-compatible embeddings.

def _build_pgvector_migration_sql(dimension: int) -> str:
    return f"""
    -- Requires Postgres with the pgvector extension enabled:
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS rag_documents (
      id BIGSERIAL PRIMARY KEY,
      doc_id TEXT UNIQUE NOT NULL,
      content TEXT NOT NULL,
      metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
      embedding VECTOR({dimension}) NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_rag_documents_embedding ON rag_documents USING ivfflat (embedding vector_cosine_ops);
    """


class PgVectorStore(VectorStore):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.dimension = get_embedding_dimension()
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for Postgres mode. Install requirements.txt first.") from exc
        self._psycopg = psycopg

    def initialize(self) -> None:
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(_build_pgvector_migration_sql(self.dimension))
            conn.commit()

    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        if not documents:
            return
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for doc in documents:
                    text = doc.get("text", "")
                    embedding = embed_text(text)
                    if len(embedding) != self.dimension:
                        raise RuntimeError(
                            f"Embedding dimension mismatch. Expected {self.dimension}, got {len(embedding)} for doc {doc.get('id')}."
                        )
                    embedding_literal = vector_to_pg_literal(embedding)
                    cur.execute(
                        """
                        INSERT INTO rag_documents (doc_id, content, metadata, embedding)
                        VALUES (%s, %s, %s::jsonb, %s::vector)
                        ON CONFLICT (doc_id)
                        DO UPDATE SET
                          content = EXCLUDED.content,
                          metadata = EXCLUDED.metadata,
                          embedding = EXCLUDED.embedding
                        """,
                        (
                            doc.get("id"),
                            text,
                            json.dumps(doc.get("metadata", {})),
                            embedding_literal,
                        ),
                    )
            conn.commit()

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        if k <= 0:
            return []
        query_embedding = embed_text(query)
        if len(query_embedding) != self.dimension:
            raise RuntimeError(
                f"Query embedding dimension mismatch. Expected {self.dimension}, got {len(query_embedding)}."
            )
        query_literal = vector_to_pg_literal(query_embedding)
        with self._psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT doc_id, content, metadata, 1 - (embedding <=> %s::vector) AS score
                    FROM rag_documents
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (query_literal, query_literal, k),
                )
                rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            doc_id, content, metadata, score = row
            results.append(
                {
                    "id": doc_id,
                    "text": content,
                    "metadata": metadata or {},
                    "score": float(score),
                }
            )
        return results

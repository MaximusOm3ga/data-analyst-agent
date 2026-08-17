import os
from pathlib import Path

from dotenv import load_dotenv

from .in_memory import InMemoryVectorStore
from .pgvector import PgVectorStore

load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / ".env")


def _build_vector_store():
    backend = os.getenv("KB_VECTOR_STORE", "memory").strip().lower()
    if backend == "memory":
        return InMemoryVectorStore(), "memory"
    if backend == "postgres":
        dsn = os.getenv("KB_POSTGRES_DSN")
        if not dsn:
            raise RuntimeError("KB_POSTGRES_DSN is required when KB_VECTOR_STORE=postgres.")
        return PgVectorStore(dsn=dsn), "postgres"
    raise RuntimeError(f"Unsupported KB_VECTOR_STORE '{backend}'. Use 'memory' or 'postgres'.")


default_vector_store, _store_name = _build_vector_store()


def get_store_name() -> str:
    return _store_name

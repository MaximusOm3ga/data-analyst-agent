from .in_memory import InMemoryVectorStore

# Default store instance used by the prototype. Swap this out to PgVectorStore when available.
default_vector_store = InMemoryVectorStore()

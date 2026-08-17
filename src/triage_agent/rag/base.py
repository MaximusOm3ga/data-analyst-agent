from abc import ABC, abstractmethod
from typing import List, Dict, Any

class VectorStore(ABC):
    """Abstract vector store interface used by the triage agent."""

    def initialize(self) -> None:
        """Initialize the underlying store schema/resources if needed."""
        return None

    @abstractmethod
    def add_documents(self, documents: List[Dict[str, Any]]) -> None:
        """Add documents to the store. Each document is a dict with keys: id, text, metadata."""
        raise NotImplementedError

    @abstractmethod
    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve top-k documents for the given query. Return list of dicts with keys: id, text, metadata, score."""
        raise NotImplementedError

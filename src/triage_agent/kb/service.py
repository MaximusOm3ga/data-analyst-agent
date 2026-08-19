from typing import List, Dict, Any
from ..rag.store import default_vector_store
from ..rag.ingest import ingest_documents
from ..schemas import CommonTicket, KnowledgeBaseDocument, KnowledgeBaseSearchResult, ClassificationOutput


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


def ingest_resolved_ticket(
    ticket: CommonTicket,
    classification: ClassificationOutput,
    resolution_summary: str,
    tool_result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    summary = resolution_summary or classification.summary or "Ticket resolved."
    doc_id = f"resolved-{ticket.ticket_id_source}-{ticket.timestamp_received.isoformat()}"
    doc = KnowledgeBaseDocument(
        id=doc_id,
        title=f"Resolved: {ticket.subject or ticket.ticket_id_source}",
        content=(
            f"Ticket ID: {ticket.ticket_id_source}\n"
            f"Requester: {ticket.requester_identifier}\n"
            f"Subject: {ticket.subject or 'N/A'}\n"
            f"Category: {classification.category}\n"
            f"Queue: {classification.queue}\n"
            f"Priority: {classification.priority}\n"
            f"Resolution: {summary}\n"
            f"Original issue: {ticket.body_raw}\n"
            f"Tool result: {tool_result or {}}"
        ),
        source_url=f"ticket://{ticket.ticket_id_source}",
        category=classification.category,
        metadata={
            "ticket_id_source": ticket.ticket_id_source,
            "requester_identifier": ticket.requester_identifier,
            "source_channel": ticket.source_channel,
            "queue": classification.queue,
            "priority": classification.priority,
            "status": "resolved",
            "tool_result": tool_result or {},
        },
    )
    return ingest_kb_documents([doc])

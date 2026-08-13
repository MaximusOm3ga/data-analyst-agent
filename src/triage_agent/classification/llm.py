from ..schemas import CommonTicket, ClassificationOutput, EnrichmentContext
from typing import Any
from ..rag.store import default_vector_store

# Mocked LLM classification that now uses RAG retrieval (prototype + heuristics).
# In production, replace heuristic logic with a real LLM call that consumes retrieved chunks + enrichment context.


def classify(ticket: CommonTicket, enrichment: EnrichmentContext) -> ClassificationOutput:
    # Very naive heuristics for demo purposes, augmented with retrieved KB chunks.
    body = (ticket.body_cleaned or ticket.body_raw or "").strip()

    # Retrieve relevant KB chunks
    retrieved = []
    try:
        retrieved = default_vector_store.retrieve(body, k=5)
    except Exception:
        retrieved = []

    retrieved_ids = [r.get("id") for r in retrieved]

    lb = body.lower()
    if "password" in lb or "reset" in lb:
        category = "Access Request"
        subcategory = "Password Reset"
        priority = "P3-Medium"
        queue = "ServiceDesk-L1"
        recommended_action = "auto_resolve"
        confidence = 0.9
        summary = "Password reset request"
    elif "vpn" in lb or "network" in lb:
        category = "Network/VPN"
        subcategory = "VPN Connectivity"
        priority = "P2-High"
        queue = "Network-Eng"
        recommended_action = "auto_route"
        confidence = 0.86
        summary = "VPN connectivity issue"
    else:
        # If KB strongly matches, bump confidence and suggest auto_route / self-help
        if retrieved and retrieved[0].get("score", 0.0) > 0.6:
            category = "Software Install"
            subcategory = retrieved[0].get("metadata", {}).get("title", "")
            priority = "P3-Medium"
            queue = "ServiceDesk-L1"
            recommended_action = "auto_route"
            confidence = 0.82
            summary = (ticket.subject or retrieved[0].get("metadata", {}).get("title", "Ticket"))[:120]
        else:
            category = "Other"
            subcategory = ""
            priority = "P4-Low"
            queue = "ServiceDesk-L1"
            recommended_action = "human_review"
            confidence = 0.5
            summary = (ticket.subject or "Ticket")[:120]

    reasoning = f"Heuristic+RAG prototype. Retrieved docs={retrieved_ids}"

    return ClassificationOutput(
        category=category,
        subcategory=subcategory,
        priority=priority,
        queue=queue,
        confidence=confidence,
        summary=summary,
        extracted_entities={"error_codes": [], "application_names": [], "device_ids_mentioned": []},
        urgency_flags=["vip_requester"] if enrichment.requester_context.get("is_vip") else ["none"],
        suggested_kb_article_ids=retrieved_ids,
        recommended_action=recommended_action,
        reasoning=reasoning
    )

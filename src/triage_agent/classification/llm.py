import json
import os
from typing import Any, Dict, List, Optional

import httpx

from ..rag.store import default_vector_store
from ..schemas import ClassificationOutput, CommonTicket, EnrichmentContext

ALLOWED_CATEGORIES = [
    "Access Request",
    "Hardware",
    "Software Install",
    "Network/VPN",
    "Account/Password",
    "Security Incident",
    "HR Request",
    "Facilities",
    "Other",
]
ALLOWED_PRIORITIES = ["P1-Critical", "P2-High", "P3-Medium", "P4-Low"]
ALLOWED_QUEUES = [
    "ServiceDesk-L1",
    "Network-Eng",
    "Security",
    "HR-Ops",
    "Facilities",
    "Software-Provisioning",
]
ALLOWED_ACTIONS = ["auto_resolve", "auto_route", "human_review"]


def _heuristic_classify(
    ticket: CommonTicket, enrichment: EnrichmentContext, retrieved: List[Dict[str, Any]]
) -> ClassificationOutput:
    body = (ticket.body_cleaned or ticket.body_raw or "").strip()
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
        reasoning=f"Heuristic fallback. Retrieved docs={retrieved_ids}",
    )


def _extract_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start : end + 1])


def _normalize_output(raw: Dict[str, Any], retrieved_ids: List[str]) -> ClassificationOutput:
    category = raw.get("category", "Other")
    if category not in ALLOWED_CATEGORIES:
        category = "Other"

    priority = raw.get("priority", "P4-Low")
    if priority not in ALLOWED_PRIORITIES:
        priority = "P4-Low"

    queue = raw.get("queue", "ServiceDesk-L1")
    if queue not in ALLOWED_QUEUES:
        queue = "ServiceDesk-L1"

    action = raw.get("recommended_action", "human_review")
    if action not in ALLOWED_ACTIONS:
        action = "human_review"

    try:
        confidence = float(raw.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    extracted_entities = raw.get("extracted_entities", {})
    if not isinstance(extracted_entities, dict):
        extracted_entities = {}

    urgency_flags = raw.get("urgency_flags", ["none"])
    if not isinstance(urgency_flags, list):
        urgency_flags = ["none"]

    suggested = raw.get("suggested_kb_article_ids", [])
    if not isinstance(suggested, list):
        suggested = []
    if not suggested:
        suggested = retrieved_ids

    return ClassificationOutput(
        category=category,
        subcategory=raw.get("subcategory") or "",
        priority=priority,
        queue=queue,
        confidence=confidence,
        summary=(raw.get("summary") or "Ticket triage")[:160],
        extracted_entities={
            "error_codes": extracted_entities.get("error_codes", []),
            "application_names": extracted_entities.get("application_names", []),
            "device_ids_mentioned": extracted_entities.get("device_ids_mentioned", []),
        },
        urgency_flags=urgency_flags,
        suggested_kb_article_ids=suggested,
        recommended_action=action,
        reasoning=raw.get("reasoning") or "LLM classification.",
    )


def _call_openai_compatible_llm(
    ticket: CommonTicket,
    enrichment: EnrichmentContext,
    retrieved: List[Dict[str, Any]],
) -> ClassificationOutput:
    api_key = os.getenv("TRIAGE_LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TRIAGE_LLM_API_KEY is required for LLM classifier mode.")

    base_url = os.getenv("TRIAGE_LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    model = os.getenv("TRIAGE_LLM_MODEL", "openai/gpt-oss-120b")
    timeout_s = float(os.getenv("TRIAGE_LLM_TIMEOUT_SECONDS", "45"))

    body = (ticket.body_cleaned or ticket.body_raw or "").strip()
    retrieved_context = [
        {
            "id": item.get("id"),
            "score": item.get("score", 0.0),
            "metadata": item.get("metadata", {}),
            "text": item.get("text", ""),
        }
        for item in retrieved
    ]
    retrieved_ids = [r.get("id") for r in retrieved_context if r.get("id")]

    system_prompt = (
        "You are an IT ticket triage classifier.\n"
        "Return ONLY one JSON object with the exact fields listed below.\n"
        "Do not include markdown or any extra text.\n"
        "Allowed values:\n"
        f"category: {ALLOWED_CATEGORIES}\n"
        f"priority: {ALLOWED_PRIORITIES}\n"
        f"queue: {ALLOWED_QUEUES}\n"
        f"recommended_action: {ALLOWED_ACTIONS}\n"
        "JSON fields required:\n"
        "{"
        "\"category\": string,"
        "\"subcategory\": string,"
        "\"priority\": string,"
        "\"queue\": string,"
        "\"confidence\": number between 0 and 1,"
        "\"summary\": string,"
        "\"extracted_entities\": {\"error_codes\": [], \"application_names\": [], \"device_ids_mentioned\": []},"
        "\"urgency_flags\": [],"
        "\"suggested_kb_article_ids\": [],"
        "\"recommended_action\": string,"
        "\"reasoning\": string"
        "}"
    )

    user_payload = {
        "ticket": {
            "ticket_id_source": ticket.ticket_id_source,
            "source_channel": ticket.source_channel,
            "requester_identifier": ticket.requester_identifier,
            "subject": ticket.subject,
            "body": body,
            "timestamp_received": ticket.timestamp_received.isoformat(),
        },
        "enrichment": {
            "requester_context": enrichment.requester_context,
            "asset_context": enrichment.asset_context,
            "history_context": enrichment.history_context,
        },
        "retrieved_kb_chunks": retrieved_context,
    }

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload)},
        ],
        "response_format": {"type": "json_object"},
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    endpoint = f"{base_url}/chat/completions"
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.post(endpoint, headers=headers, json=payload)
        if resp.status_code >= 400:
            fallback_payload = {k: v for k, v in payload.items() if k != "response_format"}
            resp = client.post(endpoint, headers=headers, json=fallback_payload)
            resp.raise_for_status()
        data = resp.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Unexpected LLM response format: {data}") from exc

    raw = _extract_json(content)
    return _normalize_output(raw, retrieved_ids)


def classify(
    ticket: CommonTicket,
    enrichment: EnrichmentContext,
    retrieved_chunks: Optional[List[Dict[str, Any]]] = None,
) -> ClassificationOutput:
    body = (ticket.body_cleaned or ticket.body_raw or "").strip()
    retrieved = retrieved_chunks or []
    if not retrieved:
        try:
            retrieved = default_vector_store.retrieve(body, k=5)
        except Exception:
            retrieved = []

    mode = os.getenv("TRIAGE_CLASSIFIER_MODE", "auto").strip().lower()
    if mode not in {"auto", "llm", "mock"}:
        mode = "auto"

    if mode == "mock":
        return _heuristic_classify(ticket, enrichment, retrieved)

    try:
        has_key = bool(os.getenv("TRIAGE_LLM_API_KEY", "").strip())
        if mode == "llm" or (mode == "auto" and has_key):
            return _call_openai_compatible_llm(ticket, enrichment, retrieved)
    except Exception:
        if mode == "llm":
            raise

    return _heuristic_classify(ticket, enrichment, retrieved)

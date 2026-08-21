import os
from typing import Any, Dict, List
from ..classification import llm
from ..enrichment import enricher
from ..kb.service import ingest_resolved_ticket, search_kb
from ..logging import shadow_log
from ..schemas import AgentLoopResult, ClassificationOutput, CommonTicket, EnrichmentContext
from ..tools.executor import execute_tool_action

MAX_ATTEMPTS = 3
PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}
SECURITY_TERMS = (
    "phishing",
    "credentials leaked",
    "ransomware",
    "unauthorized access",
    "data breach",
)


def security_guardrail(ticket: CommonTicket, enrichment: EnrichmentContext) -> Dict[str, Any]:
    body = (ticket.body_cleaned or ticket.body_raw or "").lower()
    reasons = [term for term in SECURITY_TERMS if term in body]
    employment_status = str(
        enrichment.requester_context.get("employment_status", "active")
    ).lower()
    if employment_status in {"terminated", "suspended"}:
        reasons.append(f"employment_status:{employment_status}")
    return {"triggered": len(reasons) > 0, "reasons": reasons}


def policy_gate(decision: ClassificationOutput, guardrail: Dict[str, Any]) -> str:
    if guardrail["triggered"]:
        return "force_security_route"
    if decision.confidence >= 0.85 and decision.recommended_action in {"auto_route", "auto_resolve"}:
        return decision.recommended_action
    if decision.confidence >= 0.6:
        return "auto_route_spotcheck"
    return "human_review"


def _build_override_decision(
    original: ClassificationOutput, guardrail_reasons: List[str]
) -> ClassificationOutput:
    urgency_flags = [*original.urgency_flags]
    if "security_keyword" not in urgency_flags:
        urgency_flags.append("security_keyword")
    return ClassificationOutput(
        category="Security Incident",
        subcategory="Security Guardrail Override",
        priority="P1-Critical",
        queue="Security",
        confidence=1.0,
        summary=original.summary or "Security override",
        extracted_entities=original.extracted_entities,
        urgency_flags=urgency_flags,
        suggested_kb_article_ids=original.suggested_kb_article_ids,
        recommended_action="auto_route",
        reasoning=f"Guardrail override reasons={guardrail_reasons}. Original: {original.reasoning}",
    )


def requires_human_approval(action: str, decision: ClassificationOutput, guardrail: Dict[str, Any]) -> bool:
    enabled = os.getenv("TRIAGE_APPROVAL_REQUIRED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    if action in {"force_security_route", "auto_route_spotcheck", "human_review"}:  # ← added "human_review"
        return True
    if guardrail.get("triggered") and action in {"auto_route", "auto_resolve", "force_security_route"}:
        return True
    if decision.priority in {"P1-Critical", "P2-High"} and action in {"auto_route", "auto_resolve"}:
        return True
    return False


def run_ticket_loop(ticket: CommonTicket) -> AgentLoopResult:
    attempt = 0
    final_decision = ClassificationOutput(
        category="Other",
        subcategory="",
        priority="P4-Low",
        queue="ServiceDesk-L1",
        confidence=0.0,
        summary="No decision generated",
        extracted_entities={"error_codes": [], "application_names": [], "device_ids_mentioned": []},
        urgency_flags=["none"],
        suggested_kb_article_ids=[],
        recommended_action="human_review",
        reasoning="Loop did not execute.",
    )
    final_action = "human_review"
    final_tool_result: Dict[str, Any] = {}
    final_guardrail = {"triggered": False, "reasons": []}
    status = "completed"

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        enrichment = enricher.enrich(ticket)
        kb_results = search_kb(ticket.body_cleaned or ticket.body_raw, limit=5)
        retrieved_chunks = [
            {
                "id": item.id,
                "text": item.text,
                "score": item.score,
                "metadata": item.metadata,
            }
            for item in kb_results
        ]
        decision = llm.classify(ticket, enrichment, retrieved_chunks=retrieved_chunks)
        guardrail = security_guardrail(ticket, enrichment)
        if guardrail["triggered"]:
            decision = _build_override_decision(decision, guardrail["reasons"])

        action = policy_gate(decision, guardrail)
        approval_required = requires_human_approval(action, decision, guardrail)
        if approval_required:
            final_decision = decision
            final_action = action
            final_guardrail = guardrail
            final_tool_result = {
                "success": False,
                "requires_approval": True,
                "action": action,
                "reason": "High-risk automated action requires human approval before execution.",
            }
            PENDING_APPROVALS[ticket.ticket_id_source] = {
                "ticket": ticket,
                "decision": decision,
                "action": action,
                "attempt": attempt,
                "guardrail": guardrail,
                "reason": "High-risk automated action requires human approval before execution.",
            }
            shadow_log.log_prediction(ticket, enrichment, decision)
            shadow_log.log_loop_event(
                ticket=ticket,
                attempt=attempt,
                action=action,
                tool_result=final_tool_result,
                guardrail=guardrail,
                approval_required=True,
                approval_reason=final_tool_result["reason"],
            )
            status = "awaiting_approval"
            return AgentLoopResult(
                ticket_id_source=ticket.ticket_id_source,
                status=status,
                action=final_action,
                attempts=attempt,
                decision=final_decision,
                guardrail_triggered=bool(final_guardrail["triggered"]),
                guardrail_reasons=list(final_guardrail["reasons"]),
                tool_result=final_tool_result,
                requires_approval=True,
                approval_reason=final_tool_result["reason"],
            )

        tool_result = execute_tool_action(ticket, decision, action, attempt=attempt)
        shadow_log.log_prediction(ticket, enrichment, decision)
        shadow_log.log_loop_event(
            ticket=ticket,
            attempt=attempt,
            action=action,
            tool_result=tool_result,
            guardrail=guardrail,
        )

        final_decision = decision
        final_action = action
        final_tool_result = tool_result
        final_guardrail = guardrail

        if tool_result.get("success"):
            if decision.recommended_action == "auto_resolve":
                success_summary = (
                    tool_result.get("summary")
                    or tool_result.get("message")
                    or decision.summary
                    or "Ticket resolved successfully."
                )
                ingest_resolved_ticket(
                    ticket=ticket,
                    classification=decision,
                    resolution_summary=success_summary,
                    tool_result=tool_result,
                )
                shadow_log.log_resolved_ticket(
                    ticket=ticket,
                    classification=decision,
                    summary=success_summary,
                    tool_result=tool_result,
                )
            break

    if not final_tool_result.get("success"):
        status = "failed"

    return AgentLoopResult(
        ticket_id_source=ticket.ticket_id_source,
        status=status,
        action=final_action,
        attempts=attempt,
        decision=final_decision,
        guardrail_triggered=bool(final_guardrail["triggered"]),
        guardrail_reasons=list(final_guardrail["reasons"]),
        tool_result=final_tool_result,
    )

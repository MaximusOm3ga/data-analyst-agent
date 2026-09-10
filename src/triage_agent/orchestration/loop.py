import os
import sys
import asyncio
from pathlib import Path
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

_EVAL_LOG_PATH = Path(__file__).resolve().parents[2] / "agent_eval_trigger.log"
_EVAL_FRAMEWORK_PATH = Path(__file__).resolve().parents[3] / "AI-Agent-Evaluation-Framework"
_EVAL_DB_PATH = _EVAL_FRAMEWORK_PATH / "agenteval.sqlite3"


def trigger_parallel_evaluation(
    ticket: CommonTicket,
    decision: ClassificationOutput,
    tool_result: Dict[str, Any],
    status: str,
    action: str,
    classifier_mode_used: str,
) -> None:
    payload = {
        "ticket_id_source": ticket.ticket_id_source,
        "status": status,
        "action": action,
        "decision": decision.model_dump(),
        "tool_result": tool_result,
        "classifier_mode_used": classifier_mode_used,
    }

    def _run_eval() -> None:
        try:
            eval_src = _EVAL_FRAMEWORK_PATH / "src"
            if str(eval_src) not in sys.path:
                sys.path.insert(0, str(eval_src))

            from agenteval import Dataset, DatasetCase, EvaluationSuite, evaluate
            from agenteval.core.evaluator import Evaluator
            from agenteval.core.models import DatasetCase as CoreDatasetCase, Run, Trace
            from agenteval.core.results import EvaluationResult
            from agenteval.storage.database import SQLiteDatabase
            from agenteval.storage.repositories import Repository

            class _ResolvedTicketEvaluator(Evaluator):
                name = "ResolvedTicketEvaluator"

                def evaluate(self, case: CoreDatasetCase, run: Run, trace: Trace) -> EvaluationResult:
                    actual = run.output if isinstance(run.output, dict) else {}
                    expected = case.expected if isinstance(case.expected, dict) else {}
                    checks = {
                        "status": actual.get("status") == expected.get("status"),
                        "action": actual.get("action") == expected.get("action"),
                        "category": (actual.get("decision") or {}).get("category") == expected.get("category"),
                        "queue": (actual.get("decision") or {}).get("queue") == expected.get("queue"),
                        "priority": (actual.get("decision") or {}).get("priority") == expected.get("priority"),
                        "recommended_action": (actual.get("decision") or {}).get("recommended_action")
                        == expected.get("recommended_action"),
                        "response_present": isinstance(actual.get("tool_result"), dict),
                    }
                    passed = sum(1 for ok in checks.values() if ok)
                    score = passed / len(checks)
                    return EvaluationResult(
                        evaluator=self.name,
                        score=score,
                        passed=score == 1.0,
                        explanation=f"Matched {passed}/{len(checks)} response checks for resolved ticket.",
                        metadata={"expected": expected, "actual": actual, "checks": checks},
                        evidence=[event.id for event in trace.ordered_events()[-5:]],
                    )

            def _agent(case_input: dict, tracer=None):
                return {
                    "status": case_input["status"],
                    "action": case_input.get("action"),
                    "decision": case_input.get("decision"),
                    "tool_result": case_input.get("tool_result"),
                }

            dataset = Dataset(
                id="resolved-ticket-live",
                name="resolved-ticket-live",
                cases=[
                    DatasetCase(
                        id=payload["ticket_id_source"],
                        input=payload,
                        expected={
                            "status": "resolved",
                            "action": payload["action"],
                            "category": payload["decision"].get("category"),
                            "queue": payload["decision"].get("queue"),
                            "priority": payload["decision"].get("priority"),
                            "recommended_action": payload["decision"].get("recommended_action"),
                        },
                    )
                ],
            )
            result = evaluate(agent=_agent, dataset=dataset, suite=EvaluationSuite([_ResolvedTicketEvaluator()]))
            repository = Repository(SQLiteDatabase(_EVAL_DB_PATH))
            case_result = result.cases[0]
            repository.save_run(case_result.run, case_result.trace)
            repository.save_evaluation_results(case_result.run.id, case_result.results)
            eval_result = case_result.results[0]
            with _EVAL_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"ticket={payload['ticket_id_source']} run_id={case_result.run.id} passed={eval_result.passed} score={eval_result.score} action={action}\n"
                )
        except Exception as exc:
            with _EVAL_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"eval_failed ticket={payload['ticket_id_source']} error={exc}\n")

    asyncio.create_task(asyncio.to_thread(_run_eval))


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
    final_classifier_mode_used = "unknown"
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
        decision, classifier_mode_used = llm.classify(ticket, enrichment, retrieved_chunks=retrieved_chunks)
        guardrail = security_guardrail(ticket, enrichment)
        if guardrail["triggered"]:
            decision = _build_override_decision(decision, guardrail["reasons"])

        action = policy_gate(decision, guardrail)
        approval_required = requires_human_approval(action, decision, guardrail)
        if approval_required:
            final_decision = decision
            final_action = action
            final_guardrail = guardrail
            final_classifier_mode_used = classifier_mode_used
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
                "classifier_mode_used": classifier_mode_used,
            }
            shadow_log.log_prediction(ticket, enrichment, decision, classifier_mode_used=classifier_mode_used)
            shadow_log.log_loop_event(
                ticket=ticket,
                attempt=attempt,
                action=action,
                tool_result=final_tool_result,
                guardrail=guardrail,
                approval_required=True,
                approval_reason=final_tool_result["reason"],
                classifier_mode_used=classifier_mode_used,
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
                classifier_mode_used=final_classifier_mode_used,
            )

        tool_result = execute_tool_action(ticket, decision, action, attempt=attempt)
        shadow_log.log_prediction(ticket, enrichment, decision, classifier_mode_used=classifier_mode_used)
        shadow_log.log_loop_event(
            ticket=ticket,
            attempt=attempt,
            action=action,
            tool_result=tool_result,
            guardrail=guardrail,
            classifier_mode_used=classifier_mode_used,
        )

        final_decision = decision
        final_action = action
        final_tool_result = tool_result
        final_guardrail = guardrail
        final_classifier_mode_used = classifier_mode_used

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
                    classifier_mode_used=classifier_mode_used,
                )
                trigger_parallel_evaluation(
                    ticket=ticket,
                    decision=decision,
                    tool_result=tool_result,
                    status="resolved",
                    action=action,
                    classifier_mode_used=classifier_mode_used,
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
        classifier_mode_used=final_classifier_mode_used,
    )
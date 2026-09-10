import json
import os
import threading
from pathlib import Path
from typing import Any, Dict

import httpx

from ..audit.service import record_audit_event, record_resolved_ticket
from ..schemas import ClassificationOutput, CommonTicket, EnrichmentContext

LOG_FILE = Path(__file__).parents[3] / "shadow_predictions.log"
LOOP_LOG_FILE = Path(__file__).parents[3] / "agent_loop_audit.log"
RESOLVED_TICKETS_LOG_FILE = Path(__file__).parents[3] / "resolved_tickets.log"
MIRROR_INBOX_FILE = Path(__file__).parents[3] / "mirror_inbox.log"
MIRROR_WEBHOOK = os.getenv("EVAL_MIRROR_WEBHOOK", "").strip()
MIRROR_TIMEOUT = float(os.getenv("EVAL_MIRROR_TIMEOUT_SECONDS", "5"))


def _agent_ref() -> str:
    root = Path(r"C:\Users\sauri\PycharmProjects\AI-Agent-Evaluation-Framework\eval_data_analyst_agent.py")
    return f"{root}:triage_agent"


def _evaluate_payload_async(payload: Dict[str, Any]) -> None:
    evaluator = os.getenv("EVAL_MIRROR_WEBHOOK", "").strip()
    if evaluator:
        try:
            with httpx.Client(timeout=MIRROR_TIMEOUT) as client:
                client.post(evaluator, json=payload)
        except Exception:
            with MIRROR_INBOX_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")


def _queue_eval(payload: Dict[str, Any]) -> None:
    worker = threading.Thread(target=_evaluate_payload_async, args=(payload,), daemon=True)
    worker.start()


def mirror_payload(payload: Dict[str, Any]) -> None:
    inbox_file = os.getenv("EVAL_MIRROR_FILE", "").strip()
    if inbox_file:
        with Path(inbox_file).open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
        _queue_eval(payload)
        return

    webhook = os.getenv("EVAL_MIRROR_WEBHOOK", "").strip()
    if webhook:
        try:
            timeout = float(os.getenv("EVAL_MIRROR_TIMEOUT_SECONDS", "5"))
            with httpx.Client(timeout=timeout) as client:
                client.post(webhook, json=payload)
        except Exception:
            with MIRROR_INBOX_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        _queue_eval(payload)
        return

    with MIRROR_INBOX_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    _queue_eval(payload)


def log_prediction(
    ticket: CommonTicket,
    enrichment: EnrichmentContext,
    classification: ClassificationOutput,
    classifier_mode_used: str = "unknown",
):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "requester": ticket.requester_identifier,
        "category": classification.category,
        "queue": classification.queue,
        "confidence": classification.confidence,
        "classifier_mode_used": classifier_mode_used,
        "timestamp": ticket.timestamp_received.isoformat(),
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    mirror_payload({"kind": "prediction", **entry})


def log_loop_event(
    ticket: CommonTicket,
    attempt: int,
    action: str,
    tool_result: Dict[str, Any],
    guardrail: Dict[str, Any],
    approval_required: bool = False,
    approval_reason: str = "",
    classifier_mode_used: str = "unknown",
):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "attempt": attempt,
        "action": action,
        "tool_result": tool_result,
        "guardrail": guardrail,
        "approval_required": approval_required,
        "approval_reason": approval_reason,
        "classifier_mode_used": classifier_mode_used,
        "timestamp": ticket.timestamp_received.isoformat(),
    }
    with LOOP_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    mirror_payload({"kind": "loop_event", **entry})

    record_audit_event(
        "loop_event",
        entry,
        ticket_id_source=ticket.ticket_id_source,
        requester_identifier=ticket.requester_identifier,
    )


def log_resolved_ticket(
    ticket: CommonTicket,
    classification: ClassificationOutput,
    summary: str,
    tool_result: Dict[str, Any],
    classifier_mode_used: str = "unknown",
):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "requester": ticket.requester_identifier,
        "subject": ticket.subject,
        "category": classification.category,
        "queue": classification.queue,
        "priority": classification.priority,
        "resolution_summary": summary,
        "tool_result": tool_result,
        "classifier_mode_used": classifier_mode_used,
        "timestamp": ticket.timestamp_received.isoformat(),
        "resolved": True,
    }
    with RESOLVED_TICKETS_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    mirror_payload({"kind": "resolved_ticket", **entry})

    record_resolved_ticket(
        {
            "ticket_id_source": ticket.ticket_id_source,
            "requester_identifier": ticket.requester_identifier,
            "subject": ticket.subject,
            "body_raw": ticket.body_raw,
        },
        summary,
        classification.category,
        classification.queue,
        classification.priority,
        source_channel=ticket.source_channel,
        classifier_mode_used=classifier_mode_used,
    )

import json
import os
from pathlib import Path
from typing import Any, Dict

from ..audit.service import record_audit_event, record_resolved_ticket
from ..schemas import ClassificationOutput, CommonTicket, EnrichmentContext

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOG_FILE = PROJECT_ROOT / "shadow_predictions.log"
LOOP_LOG_FILE = PROJECT_ROOT / "agent_loop_audit.log"
RESOLVED_TICKETS_LOG_FILE = PROJECT_ROOT / "resolved_tickets.log"
MIRROR_INBOX_FILE = Path(os.getenv("EVAL_MIRROR_FILE", str(PROJECT_ROOT / "mirror_inbox.log"))).expanduser().resolve(strict=False)


def _queue_eval(payload: Dict[str, Any]) -> None:
    return


def mirror_payload(payload: Dict[str, Any]) -> None:
    inbox_path = Path(os.getenv("EVAL_MIRROR_FILE", str(MIRROR_INBOX_FILE))).expanduser().resolve(strict=False)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


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

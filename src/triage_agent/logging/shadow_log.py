import json
from pathlib import Path
from typing import Any, Dict

from ..audit.service import record_audit_event, record_resolved_ticket
from ..schemas import CommonTicket, ClassificationOutput, EnrichmentContext

LOG_FILE = Path(__file__).parents[3] / "shadow_predictions.log"
LOOP_LOG_FILE = Path(__file__).parents[3] / "agent_loop_audit.log"
RESOLVED_TICKETS_LOG_FILE = Path(__file__).parents[3] / "resolved_tickets.log"


def log_prediction(ticket: CommonTicket, enrichment: EnrichmentContext, classification: ClassificationOutput):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "requester": ticket.requester_identifier,
        "category": classification.category,
        "queue": classification.queue,
        "confidence": classification.confidence,
        "timestamp": ticket.timestamp_received.isoformat()
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def log_loop_event(
    ticket: CommonTicket,
    attempt: int,
    action: str,
    tool_result: Dict[str, Any],
    guardrail: Dict[str, Any],
    approval_required: bool = False,
    approval_reason: str = "",
):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "attempt": attempt,
        "action": action,
        "tool_result": tool_result,
        "guardrail": guardrail,
        "approval_required": approval_required,
        "approval_reason": approval_reason,
        "timestamp": ticket.timestamp_received.isoformat(),
    }
    with LOOP_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

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
        "timestamp": ticket.timestamp_received.isoformat(),
        "resolved": True,
    }
    with RESOLVED_TICKETS_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

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
    )

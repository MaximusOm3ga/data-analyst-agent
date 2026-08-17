import json
from pathlib import Path
from typing import Any, Dict

from ..schemas import CommonTicket, ClassificationOutput, EnrichmentContext

LOG_FILE = Path(__file__).parents[3] / "shadow_predictions.log"
LOOP_LOG_FILE = Path(__file__).parents[3] / "agent_loop_audit.log"

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
):
    entry = {
        "ticket_id_source": ticket.ticket_id_source,
        "attempt": attempt,
        "action": action,
        "tool_result": tool_result,
        "guardrail": guardrail,
        "timestamp": ticket.timestamp_received.isoformat(),
    }
    with LOOP_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

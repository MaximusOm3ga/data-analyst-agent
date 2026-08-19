from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel


class ToolRequest(BaseModel):
    ticket: Dict[str, Any]
    decision: Dict[str, Any]
    execution: Dict[str, Any]


app = FastAPI(title="Example Tool Service for IT Ticket Triage")

AUDIT_LOG = Path(__file__).resolve().parent / "tool_service_audit.log"
TICKET_STATE: Dict[str, Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_event(event: Dict[str, Any]) -> None:
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


def _ticket_id(payload: ToolRequest) -> str:
    return str((payload.ticket or {}).get("ticket_id_source", "unknown-ticket"))


def _record_state(ticket_id: str, update: Dict[str, Any]) -> None:
    current = TICKET_STATE.get(ticket_id, {"ticket_id_source": ticket_id, "history": []})
    history = current.get("history", [])
    history.append({"ts": _now(), **update})
    current.update(update)
    current["history"] = history
    TICKET_STATE[ticket_id] = current


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "tool_service"}


@app.post("/tools/route")
def route_ticket(payload: ToolRequest) -> Dict[str, Any]:
    decision = payload.decision or {}
    ticket_id = _ticket_id(payload)
    queue = decision.get("queue") or "ServiceDesk-L1"
    priority = decision.get("priority") or "P3-Medium"
    event = {
        "ts": _now(),
        "tool": "route",
        "ticket_id": ticket_id,
        "queue": queue,
        "priority": priority,
        "execution": payload.execution,
    }
    _record_state(ticket_id, {"status": "routed", "queue": queue, "priority": priority})
    _log_event(event)
    return {
        "success": True,
        "tool": "route",
        "ticket_id": ticket_id,
        "queue": queue,
        "priority": priority,
        "message": "Ticket routed to queue by tool service.",
        "event": event,
    }


@app.post("/tools/password-reset")
def password_reset(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    requester = (payload.ticket or {}).get("requester_identifier", "unknown-user")
    event = {
        "ts": _now(),
        "tool": "password-reset",
        "ticket_id": ticket_id,
        "requester_identifier": requester,
        "execution": payload.execution,
    }
    _record_state(
        ticket_id,
        {
            "status": "resolved",
            "resolution_type": "password_reset",
            "resolution_note": "Self-service reset link triggered and MFA verification required.",
        },
    )
    _log_event(event)
    return {
        "success": True,
        "tool": "password-reset",
        "ticket_id": ticket_id,
        "status": "resolved",
        "message": "Password reset workflow executed.",
        "next_steps": ["validate MFA", "force password change at next sign-in"],
        "event": event,
    }


@app.post("/tools/network-diagnostics")
def network_diagnostics(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    event = {
        "ts": _now(),
        "tool": "network-diagnostics",
        "ticket_id": ticket_id,
        "execution": payload.execution,
    }
    _record_state(
        ticket_id,
        {
            "status": "investigating",
            "resolution_type": "network_diagnostics",
            "diagnostic_actions": [
                "collect gateway reachability",
                "check vpn auth logs",
                "run endpoint dns tests",
            ],
        },
    )
    _log_event(event)
    return {
        "success": True,
        "tool": "network-diagnostics",
        "ticket_id": ticket_id,
        "status": "investigating",
        "message": "Network diagnostics initiated.",
        "event": event,
    }


@app.post("/tools/software-license")
def software_license(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    event = {
        "ts": _now(),
        "tool": "software-license",
        "ticket_id": ticket_id,
        "execution": payload.execution,
    }
    _record_state(
        ticket_id,
        {
            "status": "resolved",
            "resolution_type": "software_license",
            "license_action": "assigned_available_seat",
        },
    )
    _log_event(event)
    return {
        "success": True,
        "tool": "software-license",
        "ticket_id": ticket_id,
        "status": "resolved",
        "message": "Software license assignment flow completed.",
        "event": event,
    }


@app.post("/tools/security-contain")
def security_contain(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    event = {
        "ts": _now(),
        "tool": "security-contain",
        "ticket_id": ticket_id,
        "execution": payload.execution,
    }
    _record_state(
        ticket_id,
        {
            "status": "contained",
            "resolution_type": "security_containment",
            "containment_actions": ["isolate endpoint", "disable active sessions", "preserve evidence"],
        },
    )
    _log_event(event)
    return {
        "success": True,
        "tool": "security-contain",
        "ticket_id": ticket_id,
        "status": "contained",
        "message": "Security containment actions completed.",
        "event": event,
    }


@app.post("/tools/resolve")
def resolve_ticket(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    summary = (payload.decision or {}).get("summary") or "Resolved by tool service"
    event = {
        "ts": _now(),
        "tool": "resolve",
        "ticket_id": ticket_id,
        "summary": summary,
        "execution": payload.execution,
    }
    _record_state(ticket_id, {"status": "resolved", "resolution_type": "generic", "resolution_note": summary})
    _log_event(event)
    return {
        "success": True,
        "tool": "resolve",
        "ticket_id": ticket_id,
        "status": "resolved",
        "summary": summary,
        "message": "Ticket resolved via generic resolver.",
        "event": event,
    }


@app.post("/tools/human-review")
def human_review(payload: ToolRequest) -> Dict[str, Any]:
    ticket_id = _ticket_id(payload)
    decision = payload.decision or {}
    event = {
        "ts": _now(),
        "tool": "human-review",
        "ticket_id": ticket_id,
        "category": decision.get("category"),
        "queue": decision.get("queue"),
        "execution": payload.execution,
    }
    _record_state(ticket_id, {"status": "human_review", "queue": decision.get("queue") or "ServiceDesk-L1"})
    _log_event(event)
    return {
        "success": True,
        "tool": "human-review",
        "ticket_id": ticket_id,
        "queue": decision.get("queue") or "ServiceDesk-L1",
        "message": "Ticket escalated for human review by tool service.",
        "event": event,
    }


@app.get("/tools/tickets/{ticket_id}")
def ticket_state(ticket_id: str) -> Dict[str, Any]:
    return TICKET_STATE.get(ticket_id, {"ticket_id_source": ticket_id, "status": "not_found", "history": []})


@app.get("/tools/audit")
def audit_log() -> Dict[str, Any]:
    if not AUDIT_LOG.exists():
        return {"events": []}
    with AUDIT_LOG.open("r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    events = [json.loads(line) for line in lines]
    return {"events": events}

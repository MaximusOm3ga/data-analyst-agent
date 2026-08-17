from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ToolRequest(BaseModel):
    ticket: Dict[str, Any]
    decision: Dict[str, Any]
    execution: Dict[str, Any]


app = FastAPI(title="Example Tool Service for IT Ticket Triage")

AUDIT_LOG = Path(__file__).resolve().parent / "tool_service_audit.log"


def _log_event(event: Dict[str, Any]) -> None:
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, default=str) + "\n")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "tool_service"}


@app.post("/tools/route")
def route_ticket(payload: ToolRequest) -> Dict[str, Any]:
    decision = payload.decision or {}
    queue = decision.get("queue") or "ServiceDesk-L1"
    priority = decision.get("priority") or "P3-Medium"
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": "route",
        "ticket_id": payload.ticket.get("ticket_id_source"),
        "queue": queue,
        "priority": priority,
        "execution": payload.execution,
    }
    _log_event(event)
    return {
        "success": True,
        "tool": "route",
        "ticket_id": payload.ticket.get("ticket_id_source"),
        "queue": queue,
        "priority": priority,
        "message": "Ticket routed to queue by tool service.",
        "event": event,
    }


@app.post("/tools/resolve")
def resolve_ticket(payload: ToolRequest) -> Dict[str, Any]:
    ticket = payload.ticket or {}
    decision = payload.decision or {}
    summary = decision.get("summary") or "Resolved by tool service"
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": "resolve",
        "ticket_id": ticket.get("ticket_id_source"),
        "summary": summary,
        "execution": payload.execution,
    }
    _log_event(event)
    return {
        "success": True,
        "tool": "resolve",
        "ticket_id": ticket.get("ticket_id_source"),
        "status": "resolved",
        "summary": summary,
        "message": "Ticket resolved via tool service.",
        "event": event,
    }


@app.post("/tools/human-review")
def human_review(payload: ToolRequest) -> Dict[str, Any]:
    ticket = payload.ticket or {}
    decision = payload.decision or {}
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": "human-review",
        "ticket_id": ticket.get("ticket_id_source"),
        "category": decision.get("category"),
        "queue": decision.get("queue"),
        "execution": payload.execution,
    }
    _log_event(event)
    return {
        "success": True,
        "tool": "human-review",
        "ticket_id": ticket.get("ticket_id_source"),
        "queue": decision.get("queue") or "ServiceDesk-L1",
        "message": "Ticket escalated for human review by tool service.",
        "event": event,
    }


@app.get("/tools/audit")
def audit_log() -> Dict[str, Any]:
    if not AUDIT_LOG.exists():
        return {"events": []}
    with AUDIT_LOG.open("r", encoding="utf-8") as fh:
        lines = [line.strip() for line in fh if line.strip()]
    events = [json.loads(line) for line in lines]
    return {"events": events}

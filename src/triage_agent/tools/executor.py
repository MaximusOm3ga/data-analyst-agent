import os
from typing import Any, Dict

import httpx

from ..schemas import ClassificationOutput, CommonTicket


def _tool_mode() -> str:
    mode = os.getenv("TRIAGE_TOOL_CALL_MODE", "mock").strip().lower()
    if mode not in {"mock", "http"}:
        return "mock"
    return mode


def _idempotency_key(ticket: CommonTicket, action: str, attempt: int) -> str:
    return f"{ticket.ticket_id_source}:{action}:{attempt}"


def _stub_result(action: str, decision: ClassificationOutput) -> Dict[str, Any]:
    if action == "force_security_route":
        return {
            "success": True,
            "tool": "itsm_router_stub",
            "target_queue": "Security",
            "priority": "P1-Critical",
            "message": "Security override applied and ticket routed to Security queue.",
        }
    if action == "auto_route":
        return {
            "success": True,
            "tool": "itsm_router_stub",
            "target_queue": decision.queue,
            "priority": decision.priority,
            "message": "Ticket auto-routed using classifier output.",
        }
    if action == "auto_route_spotcheck":
        return {
            "success": True,
            "tool": "itsm_router_stub",
            "target_queue": decision.queue,
            "priority": decision.priority,
            "message": "Ticket routed and flagged for spot-check.",
            "spotcheck_required": True,
        }
    if action == "auto_resolve":
        category = (decision.category or "").lower()
        if category in {"account/password", "access request"}:
            return {
                "success": True,
                "tool": "password_reset_stub",
                "message": "Password reset flow simulated successfully.",
            }
        if category == "network/vpn":
            return {
                "success": True,
                "tool": "network_diagnostics_stub",
                "message": "Network diagnostics flow simulated successfully.",
            }
        if category == "software install":
            return {
                "success": True,
                "tool": "software_license_stub",
                "message": "Software provisioning flow simulated successfully.",
            }
        return {
            "success": True,
            "tool": "auto_resolver_stub",
            "message": "Auto-resolve flow simulated successfully.",
        }
    return {
        "success": True,
        "tool": "triage_queue_stub",
        "message": "Ticket moved to human triage review queue.",
    }


def _build_tool_payload(
    ticket: CommonTicket,
    decision: ClassificationOutput,
    action: str,
    attempt: int,
) -> Dict[str, Any]:
    return {
        "ticket": {
            "ticket_id_source": ticket.ticket_id_source,
            "source_channel": ticket.source_channel,
            "requester_identifier": ticket.requester_identifier,
            "subject": ticket.subject,
            "body_raw": ticket.body_raw,
            "body_cleaned": ticket.body_cleaned,
            "timestamp_received": ticket.timestamp_received.isoformat(),
            "channel_metadata": ticket.channel_metadata,
        },
        "decision": {
            "category": decision.category,
            "subcategory": decision.subcategory,
            "priority": decision.priority,
            "queue": decision.queue,
            "confidence": decision.confidence,
            "summary": decision.summary,
            "urgency_flags": decision.urgency_flags,
            "recommended_action": decision.recommended_action,
            "reasoning": decision.reasoning,
        },
        "execution": {
            "action": action,
            "attempt": attempt,
            "idempotency_key": _idempotency_key(ticket, action, attempt),
        },
    }


def _endpoint_for_action(action: str, decision: ClassificationOutput) -> str:
    if action in {"force_security_route", "auto_route", "auto_route_spotcheck"}:
        return os.getenv("TRIAGE_TOOL_HTTP_ROUTE_PATH", "/tools/route")
    if action == "auto_resolve":
        category = (decision.category or "").strip().lower()
        if category in {"account/password", "access request"}:
            return os.getenv("TRIAGE_TOOL_HTTP_PASSWORD_RESET_PATH", "/tools/password-reset")
        if category == "network/vpn":
            return os.getenv("TRIAGE_TOOL_HTTP_NETWORK_DIAGNOSTICS_PATH", "/tools/network-diagnostics")
        if category == "software install":
            return os.getenv("TRIAGE_TOOL_HTTP_SOFTWARE_LICENSE_PATH", "/tools/software-license")
        return os.getenv("TRIAGE_TOOL_HTTP_RESOLVE_PATH", "/tools/resolve")
    return os.getenv("TRIAGE_TOOL_HTTP_REVIEW_PATH", "/tools/human-review")


def _post_to_path(
    *,
    action: str,
    path: str,
    payload: Dict[str, Any],
    idempotency_key: str,
    step_name: str,
) -> Dict[str, Any]:
    base_url = os.getenv("TRIAGE_TOOL_HTTP_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return {
            "success": False,
            "tool": "tool_http_router",
            "action": action,
            "error": "TRIAGE_TOOL_HTTP_BASE_URL is required when TRIAGE_TOOL_CALL_MODE=http.",
        }

    timeout_s = float(os.getenv("TRIAGE_TOOL_HTTP_TIMEOUT_SECONDS", "20"))
    verify_tls = os.getenv("TRIAGE_TOOL_HTTP_VERIFY_TLS", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    api_key = os.getenv("TRIAGE_TOOL_HTTP_API_KEY", "").strip()

    headers = {"Content-Type": "application/json", "X-Idempotency-Key": idempotency_key}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=timeout_s, verify=verify_tls) as client:
            response = client.post(f"{base_url}{path}", headers=headers, json=payload)
            response.raise_for_status()
            try:
                body: Any = response.json()
            except ValueError:
                body = {"raw": response.text}
            return {
                "success": True,
                "tool": "tool_http_router",
                "step": step_name,
                "action": action,
                "endpoint": f"{base_url}{path}",
                "status_code": response.status_code,
                "response": body,
            }
    except httpx.HTTPStatusError as exc:
        return {
            "success": False,
            "tool": "tool_http_router",
            "step": step_name,
            "action": action,
            "endpoint": f"{base_url}{path}",
            "status_code": exc.response.status_code,
            "error": exc.response.text[:1000],
        }
    except httpx.RequestError as exc:
        return {
            "success": False,
            "tool": "tool_http_router",
            "step": step_name,
            "action": action,
            "endpoint": f"{base_url}{path}",
            "error": str(exc),
        }


def execute_tool_action(
    ticket: CommonTicket,
    decision: ClassificationOutput,
    action: str,
    attempt: int = 1,
) -> Dict[str, Any]:
    if _tool_mode() == "mock":
        return _stub_result(action, decision)

    payload = _build_tool_payload(ticket, decision, action, attempt)
    idempotency_key = payload["execution"]["idempotency_key"]

    if action == "force_security_route":
        contain_path = os.getenv("TRIAGE_TOOL_HTTP_SECURITY_CONTAIN_PATH", "/tools/security-contain")
        route_path = _endpoint_for_action(action, decision)
        contain_result = _post_to_path(
            action=action,
            path=contain_path,
            payload=payload,
            idempotency_key=f"{idempotency_key}:contain",
            step_name="security_contain",
        )
        route_result = _post_to_path(
            action=action,
            path=route_path,
            payload=payload,
            idempotency_key=f"{idempotency_key}:route",
            step_name="route_security",
        )
        return {
            "success": bool(contain_result.get("success")) and bool(route_result.get("success")),
            "tool": "tool_http_workflow",
            "action": action,
            "steps": [contain_result, route_result],
        }

    path = _endpoint_for_action(action, decision)
    return _post_to_path(
        action=action,
        path=path,
        payload=payload,
        idempotency_key=idempotency_key,
        step_name="single_step",
    )

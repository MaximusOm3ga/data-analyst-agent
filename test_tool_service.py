from fastapi.testclient import TestClient

from tool_service import app

client = TestClient(app)


def test_route_tool():
    payload = {
        "ticket": {"ticket_id_source": "T-100", "subject": "Password reset"},
        "decision": {"queue": "ServiceDesk-L1", "priority": "P2-High", "summary": "Password reset request"},
        "execution": {"action": "auto_route", "attempt": 1, "idempotency_key": "T-100:auto_route:1"},
    }
    resp = client.post("/tools/route", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["queue"] == "ServiceDesk-L1"


def test_resolve_tool():
    payload = {
        "ticket": {"ticket_id_source": "T-200"},
        "decision": {"summary": "Reset password"},
        "execution": {"action": "auto_resolve", "attempt": 1, "idempotency_key": "T-200:auto_resolve:1"},
    }
    resp = client.post("/tools/resolve", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["status"] == "resolved"


def test_password_reset_tool():
    payload = {
        "ticket": {"ticket_id_source": "T-300", "requester_identifier": "alice@example.com"},
        "decision": {"category": "Account/Password"},
        "execution": {"action": "auto_resolve", "attempt": 1, "idempotency_key": "T-300:auto_resolve:1"},
    }
    resp = client.post("/tools/password-reset", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["tool"] == "password-reset"
    assert body["status"] == "resolved"


def test_security_contain_then_route_updates_state():
    base_payload = {
        "ticket": {"ticket_id_source": "T-400", "requester_identifier": "soc@example.com"},
        "decision": {"queue": "Security", "priority": "P1-Critical", "category": "Security Incident"},
        "execution": {"action": "force_security_route", "attempt": 1, "idempotency_key": "T-400:force_security_route:1"},
    }
    contain = client.post("/tools/security-contain", json=base_payload)
    assert contain.status_code == 200, contain.text
    route = client.post("/tools/route", json=base_payload)
    assert route.status_code == 200, route.text

    state = client.get("/tools/tickets/T-400")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["ticket_id_source"] == "T-400"
    assert body["queue"] == "Security"
    assert len(body["history"]) >= 2

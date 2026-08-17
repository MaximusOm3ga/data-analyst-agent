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

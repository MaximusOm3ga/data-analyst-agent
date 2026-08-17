import os
from datetime import datetime

from fastapi.testclient import TestClient

os.environ["KB_VECTOR_STORE"] = "memory"
os.environ.pop("KB_POSTGRES_DSN", None)
os.environ["TRIAGE_CLASSIFIER_MODE"] = "mock"
os.environ["TRIAGE_LLM_API_KEY"] = ""
os.environ["TRIAGE_EMBEDDINGS_MODE"] = "mock"
os.environ["TRIAGE_EMBEDDINGS_API_KEY"] = ""

from src.triage_agent.main import app

client = TestClient(app)


def test_password_reset_auto_resolve():
    payload = {
        "ticket_id_source": "web-1",
        "source_channel": "web_form",
        "requester_identifier": "user@example.com",
        "subject": "Need password reset",
        "body_raw": "I forgot my password and need a reset",
        "body_cleaned": None,
        "attachments": [],
        "timestamp_received": datetime.utcnow().isoformat(),
        "channel_metadata": {},
    }
    resp = client.post("/ingest/web_form", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["action"] == "auto_resolve"
    assert data["decision"]["category"] == "Access Request"
    assert data["decision"]["recommended_action"] == "auto_resolve"


def test_unknown_goes_human_review():
    payload = {
        "ticket_id_source": "web-2",
        "source_channel": "web_form",
        "requester_identifier": "user2@example.com",
        "subject": "My screen flickers",
        "body_raw": "Sometimes the display flickers when I open the browser",
        "body_cleaned": None,
        "attachments": [],
        "timestamp_received": datetime.utcnow().isoformat(),
        "channel_metadata": {},
    }
    resp = client.post("/ingest/web_form", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] in {"human_review", "auto_route_spotcheck"}
    assert data["decision"]["recommended_action"] == "human_review" or data["decision"]["confidence"] < 0.6


def test_security_guardrail_forces_security_route():
    payload = {
        "ticket_id_source": "web-3",
        "source_channel": "web_form",
        "requester_identifier": "user3@example.com",
        "subject": "Urgent suspicious email",
        "body_raw": "I think this is phishing and maybe a data breach.",
        "body_cleaned": None,
        "attachments": [],
        "timestamp_received": datetime.utcnow().isoformat(),
        "channel_metadata": {},
    }
    resp = client.post("/ingest/web_form", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["guardrail_triggered"] is True
    assert data["action"] == "force_security_route"
    assert data["decision"]["queue"] == "Security"
    assert data["decision"]["priority"] == "P1-Critical"


def test_kb_ingest_and_search():
    payload = {
        "documents": [
            {
                "id": "kb-password-reset",
                "title": "Password reset guide",
                "content": "To reset your password, visit the self-service portal and choose forgotten password. Follow the security prompts.",
                "source_url": "https://example.com/kb/password-reset",
                "category": "Access Request",
                "metadata": {"owner": "IT"},
            }
        ]
    }
    resp = client.post("/kb/documents", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["documents"] == 1

    search = client.get("/kb/search", params={"query": "I forgot my password", "limit": 3})
    assert search.status_code == 200
    result = search.json()
    assert len(result) >= 1
    assert "password" in result[0]["text"].lower()


def test_kb_init_store_and_health():
    init_resp = client.post("/kb/init-store")
    assert init_resp.status_code == 200
    assert init_resp.json()["status"] == "initialized"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["kb_store"] in ("memory", "postgres")

from datetime import datetime

from fastapi.testclient import TestClient

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
    assert data["category"] == "Access Request"
    assert data["recommended_action"] == "auto_resolve"


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
    assert data["recommended_action"] == "human_review" or data["confidence"] < 0.6


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

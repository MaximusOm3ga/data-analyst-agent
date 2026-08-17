import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import streamlit as st

st.set_page_config(page_title="Ticket Triage Agent UI", page_icon="🎫", layout="wide")


def _post_json(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with httpx.Client(timeout=60) as client:
        response = client.post(f"{base_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()


def _get_json(base_url: str, path: str, params: Dict[str, Any] = None) -> Any:
    with httpx.Client(timeout=60) as client:
        response = client.get(f"{base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()


def _read_last_log_lines(repo_root: Path, filename: str, limit: int = 100) -> List[str]:
    log_path = repo_root / filename
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as file:
        lines = file.readlines()
    return lines[-limit:]


st.title("🎫 IT Ticket Triage Agent")
st.caption("UI for KB ingestion, ticket triage, and audit inspection")

default_api = "http://127.0.0.1:8000"
base_url = st.sidebar.text_input("API Base URL", default_api).rstrip("/")
repo_root = Path(__file__).resolve().parents[1]

if st.sidebar.button("Check Health"):
    try:
        health = _get_json(base_url, "/health")
        st.sidebar.success(f"API OK: {health}")
    except Exception as exc:
        st.sidebar.error(f"Health check failed: {exc}")

tabs = st.tabs(["KB Ingestion", "Ticket Triage", "KB Search", "Audit Logs"])

with tabs[0]:
    st.subheader("Upload KB Documents")
    st.write("Paste JSON payload for `/kb/documents`.")
    sample_kb_payload = {
        "documents": [
            {
                "id": "kb-001",
                "title": "Password Reset Guide",
                "content": "Go to self-service portal and reset your password using MFA.",
                "source_url": "https://example.com/kb/password-reset",
                "category": "Access Request",
                "metadata": {"owner": "IT", "priority": "high-volume"},
            }
        ]
    }
    kb_text = st.text_area(
        "KB JSON",
        value=json.dumps(sample_kb_payload, indent=2),
        height=260,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Initialize KB Store"):
            try:
                result = _post_json(base_url, "/kb/init-store", {})
                st.success(result)
            except Exception as exc:
                st.error(f"Init failed: {exc}")
    with col2:
        if st.button("Upload KB Payload"):
            try:
                payload = json.loads(kb_text)
                result = _post_json(base_url, "/kb/documents", payload)
                st.success("KB uploaded")
                st.json(result)
            except Exception as exc:
                st.error(f"Upload failed: {exc}")

with tabs[1]:
    st.subheader("Submit Ticket")
    ticket_id_source = st.text_input("Ticket ID Source", value=f"ui-{int(datetime.now().timestamp())}")
    requester_identifier = st.text_input("Requester Identifier", value="user@example.com")
    subject = st.text_input("Subject", value="Cannot sign in")
    body_raw = st.text_area("Body", value="I forgot my password and cannot log in.")
    source_channel = st.selectbox("Source Channel", ["web_form", "email", "slack", "teams", "chatbot"], index=0)

    if st.button("Run Agent Loop"):
        try:
            payload = {
                "ticket_id_source": ticket_id_source,
                "source_channel": source_channel,
                "requester_identifier": requester_identifier,
                "subject": subject,
                "body_raw": body_raw,
                "body_cleaned": None,
                "attachments": [],
                "timestamp_received": datetime.now(timezone.utc).isoformat(),
                "channel_metadata": {},
            }
            result = _post_json(base_url, "/ingest/web_form", payload)
            st.success("Ticket processed")
            st.json(result)
            decision = result.get("decision", {})
            if decision:
                st.markdown(
                    f"**Action:** `{result.get('action')}` | "
                    f"**Category:** `{decision.get('category')}` | "
                    f"**Queue:** `{decision.get('queue')}` | "
                    f"**Confidence:** `{decision.get('confidence')}`"
                )
        except Exception as exc:
            st.error(f"Triage failed: {exc}")

with tabs[2]:
    st.subheader("Search KB")
    query = st.text_input("Search Query", value="password reset")
    limit = st.slider("Top K", min_value=1, max_value=10, value=5)
    if st.button("Search"):
        try:
            result = _get_json(base_url, "/kb/search", params={"query": query, "limit": limit})
            st.json(result)
        except Exception as exc:
            st.error(f"Search failed: {exc}")

with tabs[3]:
    st.subheader("Audit Logs")
    log_choice = st.selectbox("Log File", ["agent_loop_audit.log", "shadow_predictions.log"])
    lines_limit = st.slider("Lines", min_value=20, max_value=500, value=100, step=20)
    if st.button("Refresh Logs"):
        lines = _read_last_log_lines(repo_root, log_choice, lines_limit)
        if not lines:
            st.info("No log lines found yet.")
        else:
            st.code("".join(lines), language="json")

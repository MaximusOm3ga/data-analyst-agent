from datetime import datetime, timezone
from typing import Any, Dict

import httpx
import streamlit as st

st.set_page_config(
    page_title="Ticket Support Portal",
    page_icon="🛠️",
    layout="centered",
    initial_sidebar_state="collapsed",
)


def _post_json(base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with httpx.Client(timeout=60) as client:
        response = client.post(f"{base_url}{path}", json=payload)
        response.raise_for_status()
        return response.json()


st.title("🛠️ IT Support Ticket Portal")
st.caption("Submit a ticket and receive triage resolution guidance")

default_api = "http://127.0.0.1:8000"
base_url = st.text_input("Support API URL", value=default_api).rstrip("/")

with st.form("submit_ticket_form"):
    requester_identifier = st.text_input("Work Email", value="user@example.com")
    subject = st.text_input("Subject", value="Cannot sign in")
    body_raw = st.text_area("Describe your issue", value="I forgot my password and cannot log in.", height=160)
    source_channel = st.selectbox("Contact Channel", ["web_form", "email", "slack", "teams", "chatbot"], index=0)
    submitted = st.form_submit_button("Submit Ticket")

if submitted:
    try:
        payload = {
            "ticket_id_source": f"portal-{int(datetime.now().timestamp())}",
            "source_channel": source_channel,
            "requester_identifier": requester_identifier,
            "subject": subject,
            "body_raw": body_raw,
            "body_cleaned": None,
            "attachments": [],
            "timestamp_received": datetime.now(timezone.utc).isoformat(),
            "channel_metadata": {"ui": "user_dashboard"},
        }
        result = _post_json(base_url, "/ingest/web_form", payload)
        decision = result.get("decision", {})
        tool_result = result.get("tool_result", {})

        st.success("Ticket submitted and processed.")
        st.subheader("Resolution")
        st.markdown(f"**Ticket ID:** {result.get('ticket_id_source', 'N/A')}")
        st.markdown(f"**Outcome:** {result.get('action', 'N/A').replace('_', ' ').title()}")
        st.markdown(f"**Summary:** {decision.get('summary', 'No summary provided.')}")
        st.markdown(f"**Assigned Team:** {decision.get('queue', 'ServiceDesk-L1')}")
        st.markdown(f"**Priority:** {decision.get('priority', 'P4-Low')}")

        guidance = tool_result.get("message") or decision.get("reasoning") or "Follow up with support if issue persists."

        st.subheader("Next Steps")
        st.write(guidance)

        st.caption("This successful resolution is also stored in the system knowledge base and logged for future ticket handling.")

        if result.get("action") == "auto_resolve":
            st.info("The ticket was resolved automatically and added to the learning knowledge base for similar future issues.")
    except Exception as exc:
        st.error(f"Unable to submit ticket: {exc}")

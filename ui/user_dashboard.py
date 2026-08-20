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

if "latest_ticket_request" not in st.session_state:
    st.session_state["latest_ticket_request"] = None
if "latest_ticket_result" not in st.session_state:
    st.session_state["latest_ticket_result"] = None
if "latest_ticket_marked_resolved" not in st.session_state:
    st.session_state["latest_ticket_marked_resolved"] = False

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
        st.session_state["latest_ticket_request"] = payload
        st.session_state["latest_ticket_result"] = result
        st.session_state["latest_ticket_marked_resolved"] = False

    except Exception as exc:
        st.error(f"Unable to submit ticket: {exc}")

latest_request = st.session_state.get("latest_ticket_request")
latest_result = st.session_state.get("latest_ticket_result")
already_marked = bool(st.session_state.get("latest_ticket_marked_resolved"))

if latest_request and latest_result:
    decision = latest_result.get("decision", {})
    tool_result = latest_result.get("tool_result", {})
    guidance = tool_result.get("message") or decision.get("reasoning") or "Follow up with support if issue persists."

    st.success("Ticket submitted and processed.")
    st.subheader("Suggested Resolution")
    st.markdown(f"**Ticket ID:** {latest_result.get('ticket_id_source', 'N/A')}")
    st.markdown(f"**Outcome:** {latest_result.get('action', 'N/A').replace('_', ' ').title()}")
    st.markdown(f"**Summary:** {decision.get('summary', 'No summary provided.')}")
    st.markdown(f"**Assigned Team:** {decision.get('queue', 'ServiceDesk-L1')}")
    st.markdown(f"**Priority:** {decision.get('priority', 'P4-Low')}")

    st.subheader("Next Steps")
    st.write(guidance)
    st.warning("This is a suggested resolution. It is not automatically marked as resolved until you confirm.")

    mark_button = st.button(
        "Mark as Resolved",
        key=f"resolve_{latest_result.get('ticket_id_source', 'ticket')}",
        disabled=already_marked,
    )
    if mark_button:
        resolved_payload = {
            "ticket_id_source": latest_result.get("ticket_id_source", f"portal-{int(datetime.now().timestamp())}"),
            "source_channel": latest_request.get("source_channel", "web_form"),
            "requester_identifier": latest_request.get("requester_identifier", "user@example.com"),
            "subject": latest_request.get("subject"),
            "body_raw": latest_request.get("body_raw", ""),
            "resolution_summary": decision.get("summary") or guidance,
            "category": decision.get("category") or "Other",
            "queue": decision.get("queue") or "ServiceDesk-L1",
            "priority": decision.get("priority") or "P4-Low",
            "status": "resolved",
            "timestamp_received": datetime.now(timezone.utc).isoformat(),
            "metadata": {"owner": "IT", "ui": "user_dashboard", "confirmed_by_user": True},
        }
        try:
            resolved_result = _post_json(base_url, "/tickets/resolved", resolved_payload)
            st.session_state["latest_ticket_marked_resolved"] = True
            st.success("Ticket marked as resolved and added to the knowledge base.")
            st.json(resolved_result)
        except Exception as exc:
            st.error(f"Unable to finalize resolution: {exc}")

    if st.session_state.get("latest_ticket_marked_resolved"):
        st.info("This ticket has been marked as resolved and recorded.")

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import streamlit as st

st.set_page_config(
    page_title="Ticket Triage Agent Admin Dashboard",
    page_icon="🎫",
    layout="wide",
    initial_sidebar_state="expanded",
)


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


def _docs_from_zip(
    zip_bytes: bytes,
    default_category: str,
    default_owner: str,
    max_files: int = 500,
    max_chars_per_file: int = 500_000,
) -> Dict[str, Any]:
    allowed_suffixes = {".txt", ".md", ".rst", ".log", ".csv", ".json"}
    docs: List[Dict[str, Any]] = []
    skipped: List[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        for member in members[:max_files]:
            inner_path = member.filename
            suffix = Path(inner_path).suffix.lower()
            if suffix not in allowed_suffixes:
                skipped.append(inner_path)
                continue
            try:
                content_bytes = archive.read(member)
                content = content_bytes.decode("utf-8", errors="ignore").strip()
                if not content:
                    skipped.append(inner_path)
                    continue
                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file]
                doc_id = inner_path.replace("\\", "/").replace("/", "__")
                docs.append(
                    {
                        "id": doc_id,
                        "title": Path(inner_path).stem or inner_path,
                        "content": content,
                        "source_url": f"zip://{inner_path}",
                        "category": default_category,
                        "metadata": {"owner": default_owner, "path_in_zip": inner_path},
                    }
                )
            except Exception:
                skipped.append(inner_path)

    return {"documents": docs, "skipped_files": skipped}


st.title("🎫 IT Ticket Triage Agent - Admin Dashboard")
st.caption("Admin UI for KB ingestion, ticket triage inspection, KB search, and audit logs")

default_api = "http://127.0.0.1:8000"
repo_root = Path(__file__).resolve().parents[1]

base_url = st.sidebar.text_input("API Base URL", default_api).rstrip("/")
check_health_clicked = st.sidebar.button("Check Health")

if check_health_clicked:
    try:
        health = _get_json(base_url, "/health")
        st.sidebar.success(f"API OK: {health}")
    except Exception as exc:
        st.sidebar.error(f"Health check failed: {exc}")

with st.expander("Quick access", expanded=False):
    quick_base_url = st.text_input("API Base URL (quick)", value=base_url).rstrip("/")
    if quick_base_url:
        base_url = quick_base_url
    if st.button("Check Health (quick)"):
        try:
            health = _get_json(base_url, "/health")
            st.success(f"API OK: {health}")
        except Exception as exc:
            st.error(f"Health check failed: {exc}")

tabs = st.tabs(["KB Ingestion", "Ticket Triage", "KB Search", "Resolved Tickets", "Audit Logs"])

with tabs[0]:
    st.subheader("Upload KB Documents")
    st.write("Paste JSON payload for `/kb/documents` or upload a zipped folder (`.zip`).")
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

    st.divider()
    st.subheader("Upload Zipped KB Folder")
    zip_file = st.file_uploader("Upload .zip containing KB files", type=["zip"])
    zip_category = st.text_input("Default category for zip docs", value="Other")
    zip_owner = st.text_input("Owner metadata for zip docs", value="IT")
    max_zip_files = st.slider("Max files to read from zip", min_value=10, max_value=2000, value=500, step=10, key="zip_max_files")
    max_chars_per_file = st.slider(
        "Max characters per file",
        min_value=10_000,
        max_value=1_000_000,
        value=500_000,
        step=10_000,
        key="zip_max_chars",
    )

    if st.button("Upload ZIP to KB"):
        if not zip_file:
            st.warning("Please upload a .zip file first.")
        else:
            try:
                parsed = _docs_from_zip(
                    zip_file.getvalue(),
                    default_category=zip_category,
                    default_owner=zip_owner,
                    max_files=max_zip_files,
                    max_chars_per_file=max_chars_per_file,
                )
                docs_payload = {"documents": parsed["documents"]}
                if not docs_payload["documents"]:
                    st.warning("No supported text-like files found in the zip.")
                else:
                    result = _post_json(base_url, "/kb/documents", docs_payload)
                    st.success(
                        f"Uploaded {len(docs_payload['documents'])} docs from zip. "
                        f"Skipped {len(parsed['skipped_files'])} files."
                    )
                    st.json(result)
                    with st.expander("Skipped files"):
                        st.json(parsed["skipped_files"])
            except Exception as exc:
                st.error(f"ZIP upload failed: {exc}")

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
            if result.get("requires_approval"):
                st.warning("This action requires human approval before execution.")
                if st.button("Approve Pending Action", key=f"approve_{ticket_id_source}"):
                    approval_payload = {
                        "ticket_id_source": ticket_id_source,
                        "approver": "admin-ui",
                        "reason": "Approved from admin dashboard",
                        "approved": True,
                    }
                    approval_result = _post_json(base_url, "/tickets/approve", approval_payload)
                    st.success("Approval recorded")
                    st.json(approval_result)
        except Exception as exc:
            st.error(f"Triage failed: {exc}")

    st.divider()
    st.subheader("Pending Approvals")
    if st.button("Refresh Approval Queue"):
        try:
            pending = _get_json(base_url, "/approval/pending")
            st.json(pending)
        except Exception as exc:
            st.error(f"Failed to load approval queue: {exc}")

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
    st.subheader("Resolved Ticket Registry")
    st.write("Successful resolutions are ingested into the KB and stored in the resolved ticket log.")

    resolved_log_choice = st.selectbox("Resolved ticket log", ["resolved_tickets.log", "agent_loop_audit.log", "shadow_predictions.log"], key="resolved_log_choice")
    resolved_lines_limit = st.slider("Lines", min_value=20, max_value=500, value=100, step=20, key="resolved_lines_limit")
    if st.button("Refresh Resolved Tickets", key="refresh_resolved_tickets"):
        lines = _read_last_log_lines(repo_root, resolved_log_choice, resolved_lines_limit)
        if not lines:
            st.info("No resolved ticket records found yet.")
        else:
            st.code("".join(lines), language="json")

    st.divider()
    st.subheader("Manually Add Resolved Ticket to KB")
    with st.form("manual_resolved_ticket"):
        manual_ticket_id = st.text_input("Ticket ID", value=f"manual-{int(datetime.now().timestamp())}")
        manual_requester = st.text_input("Requester", value="user@example.com")
        manual_subject = st.text_input("Subject", value="Password reset completed")
        manual_body = st.text_area("Original issue", value="User could not log in due to lost password.", height=120)
        manual_resolution = st.text_area("Resolution summary", value="User verified identity and completed password reset via MFA flow.", height=120)
        manual_category = st.text_input("Category", value="Access Request")
        manual_queue = st.text_input("Queue", value="ServiceDesk-L1")
        manual_priority = st.text_input("Priority", value="P3-Medium")
        manual_status = st.selectbox("Status", ["resolved", "closed"], index=0)
        submit_manual = st.form_submit_button("Store Resolved Ticket")

    if submit_manual:
        try:
            payload = {
                "ticket_id_source": manual_ticket_id,
                "source_channel": "ui_admin",
                "requester_identifier": manual_requester,
                "subject": manual_subject,
                "body_raw": manual_body,
                "resolution_summary": manual_resolution,
                "category": manual_category,
                "queue": manual_queue,
                "priority": manual_priority,
                "status": manual_status,
                "timestamp_received": datetime.now(timezone.utc).isoformat(),
                "metadata": {"owner": "IT", "ui": "admin_dashboard"},
            }
            result = _post_json(base_url, "/tickets/resolved", payload)
            st.success("Resolved ticket saved to KB and audit log.")
            st.json(result)
        except Exception as exc:
            st.error(f"Resolved ticket ingest failed: {exc}")

with tabs[4]:
    st.subheader("Audit Logs")
    log_choice = st.selectbox("Log File", ["agent_loop_audit.log", "shadow_predictions.log", "resolved_tickets.log"], key="audit_log_choice")
    lines_limit = st.slider("Lines", min_value=20, max_value=500, value=100, step=20, key="audit_lines_limit")
    if st.button("Refresh Logs", key="refresh_audit_logs"):
        lines = _read_last_log_lines(repo_root, log_choice, lines_limit)
        if not lines:
            st.info("No log lines found yet.")
        else:
            st.code("".join(lines), language="json")

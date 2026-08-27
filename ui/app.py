import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
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


def _delete_json(base_url: str, path: str, params: Dict[str, Any] = None) -> Any:
    with httpx.Client(timeout=60) as client:
        response = client.delete(f"{base_url}{path}", params=params)
        response.raise_for_status()
        return response.json()


def _read_last_log_lines(repo_root: Path, filename: str, limit: int = 100) -> List[str]:
    log_path = repo_root / filename
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as file:
        lines = file.readlines()
    return lines[-limit:]


ALL_LOG_FILES = ["agent_loop_audit.log", "shadow_predictions.log", "resolved_tickets.log"]


def _load_log_entries(repo_root: Path, filename: str, max_lines: int = 2000) -> List[Dict[str, Any]]:
    """Reads the most recent max_lines from a log file and parses each as JSON.
    Malformed lines are skipped rather than breaking the whole read."""
    log_path = repo_root / filename
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as file:
        raw_lines = file.readlines()[-max_lines:]
    entries: List[Dict[str, Any]] = []
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entry["_source_log"] = filename
        entries.append(entry)
    return entries


def _parse_entry_timestamp(entry: Dict[str, Any]):
    ts_raw = entry.get("timestamp")
    if not ts_raw:
        return None
    try:
        return datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _filter_log_entries(
    entries: List[Dict[str, Any]],
    search_text: str = "",
    classifier_modes: List[str] = None,
    actions: List[str] = None,
    ticket_id: str = "",
    start_dt=None,
    end_dt=None,
) -> List[Dict[str, Any]]:
    search_text = (search_text or "").strip().lower()
    ticket_id = (ticket_id or "").strip().lower()
    results = []
    for entry in entries:
        if ticket_id and ticket_id not in str(entry.get("ticket_id_source", "")).lower():
            continue
        if search_text and search_text not in json.dumps(entry).lower():
            continue
        if classifier_modes and entry.get("classifier_mode_used") not in classifier_modes:
            continue
        if actions and entry.get("action") not in actions:
            continue
        if start_dt or end_dt:
            ts = _parse_entry_timestamp(entry)
            if ts is None:
                continue
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue
        results.append(entry)
    return results


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


st.title("IT Ticket Triage Agent - Admin Dashboard")
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
    with st.expander("⚠Danger Zone — Clear Knowledge Base"):
        st.warning(
            "This permanently deletes every document in the knowledge base "
            "(all imported docs and all auto-written resolved-ticket entries). "
            "This cannot be undone."
        )
        nuke_confirm_text = st.text_input(
            "Type DELETE to enable the button below", value="", key="nuke_kb_confirm"
        )
        if st.button("Nuke Knowledge Base", disabled=(nuke_confirm_text != "DELETE")):
            try:
                result = _delete_json(base_url, "/kb/documents", params={"confirm": "DELETE"})
                st.success(f"Knowledge base cleared — {result.get('documents_removed', 0)} document(s) removed.")
            except Exception as exc:
                st.error(f"Clear failed: {exc}")

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
            classifier_mode = result.get("classifier_mode_used", "unknown")
            mode_badge = {
                "llm": "🟢 LLM (Groq)",
                "heuristic_no_api_key": "🟡 Heuristic — no API key set",
                "heuristic_llm_call_failed": "🔴 Heuristic — LLM call failed",
                "heuristic_mock_mode": "⚪ Heuristic — mock mode forced",
            }.get(classifier_mode, f"⚪ {classifier_mode}")
            st.caption(f"Classifier used: {mode_badge}")
            if decision:
                st.markdown(
                    f"**Action:** `{result.get('action')}` | "
                    f"**Category:** `{decision.get('category')}` | "
                    f"**Queue:** `{decision.get('queue')}` | "
                    f"**Confidence:** `{decision.get('confidence')}`"
                )
            if result.get("requires_approval"):
                st.warning("This action requires human approval — review it in the Pending Approvals queue below.")
        except Exception as exc:
            st.error(f"Triage failed: {exc}")

    st.divider()
    st.subheader("Pending Approvals")

    col_refresh, col_count = st.columns([1, 3])
    with col_refresh:
        refresh_clicked = st.button("🔄 Refresh Queue")

    # Always fetch fresh on every render of this tab — tickets can arrive from
    # any client (admin console, end-user portal, other channels) at any time,
    # so a cached/stale list would hide new arrivals until a manual refresh.
    try:
        pending_items = _get_json(base_url, "/approval/pending").get("pending", [])
    except Exception as exc:
        st.error(f"Failed to load approval queue: {exc}")
        pending_items = []

    with col_count:
        if pending_items:
            st.markdown(f"**{len(pending_items)} ticket(s) awaiting review**")
        else:
            st.caption("No tickets currently awaiting approval.")

    priority_color = {
        "P1-Critical": "🔴",
        "P2-High": "🟠",
        "P3-Medium": "🟡",
        "P4-Low": "🟢",
    }

    for item in pending_items:
        ticket_id = item.get("ticket_id_source")
        priority = item.get("priority", "P4-Low")
        icon = priority_color.get(priority, "⚪")

        with st.container(border=True):
            st.markdown(
                f"{icon} **{ticket_id}** &nbsp;|&nbsp; "
                f"Action: `{item.get('action')}` &nbsp;|&nbsp; "
                f"Priority: `{priority}` &nbsp;|&nbsp; "
                f"Queue: `{item.get('queue')}`"
            )
            st.caption(f"Why it's here: {item.get('reason', '')}")

            if item.get("guardrail_triggered"):
                st.error(
                    "Security guardrail triggered: " + "; ".join(item.get("guardrail_reasons", []) or ["(no reason text)"])
                )

            st.markdown(f"**Subject:** {item.get('subject') or '(no subject)'}")
            st.markdown(
                f"**From:** {item.get('requester_identifier', 'unknown')} "
                f"via `{item.get('source_channel', 'unknown')}`"
            )
            with st.expander("Original ticket body", expanded=False):
                st.write(item.get("body_raw") or "(empty)")

            st.markdown("**What the classifier is asking to do:**")
            col_cls1, col_cls2, col_cls3 = st.columns(3)
            with col_cls1:
                st.metric("Category", item.get("category") or "—")
            with col_cls2:
                st.metric("Confidence", f"{item.get('confidence', 0):.0%}" if item.get("confidence") is not None else "—")
            with col_cls3:
                st.metric("Recommended action", item.get("recommended_action") or "—")

            if item.get("urgency_flags"):
                st.markdown("**Urgency flags:** " + ", ".join(item["urgency_flags"]))

            st.markdown(f"**Classifier summary:** {item.get('summary') or '(none provided)'}")
            if item.get("reasoning"):
                with st.expander("Classifier reasoning"):
                    st.write(item["reasoning"])

            st.caption(f"Classifier used: {item.get('classifier_mode_used', 'unknown')}")

            with st.expander("Reviewer notes / resolution"):
                resolution_text = st.text_area(
                    "Resolution summary (recorded in the resolved-ticket log and KB on approval)",
                    value="",
                    placeholder="What was actually done to resolve this ticket, if anything...",
                    key=f"resolution_{ticket_id}",
                )
                reason_text = st.text_input(
                    "Reason", value="Approved from admin dashboard", key=f"reason_{ticket_id}"
                )
                approver_name = st.text_input("Approver", value="admin-ui", key=f"approver_{ticket_id}")

            col_approve, col_reject, col_spacer = st.columns([1, 1, 4])
            with col_approve:
                if st.button("Approve", key=f"approve_btn_{ticket_id}"):
                    try:
                        result = _post_json(
                            base_url,
                            "/tickets/approve",
                            {
                                "ticket_id_source": ticket_id,
                                "approver": approver_name,
                                "reason": reason_text,
                                "approved": True,
                                "resolution_summary": resolution_text or None,
                            },
                        )
                        st.success(f"Approved {ticket_id}")
                        st.json(result)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Approval failed: {exc}")
            with col_reject:
                if st.button("Reject", key=f"reject_btn_{ticket_id}"):
                    try:
                        result = _post_json(
                            base_url,
                            "/tickets/approve",
                            {
                                "ticket_id_source": ticket_id,
                                "approver": approver_name,
                                "reason": reason_text,
                                "approved": False,
                            },
                        )
                        st.warning(f"Rejected {ticket_id}")
                        st.json(result)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Rejection failed: {exc}")

with tabs[2]:
    st.subheader("Search KB")
    query = st.text_input("Search Query", value="password reset")
    limit = st.slider("Top K", min_value=1, max_value=10, value=5)
    if st.button("Search"):
        try:
            result = _get_json(base_url, "/kb/search", params={"query": query, "limit": limit})
            st.session_state["kb_search_results"] = result
        except Exception as exc:
            st.error(f"Search failed: {exc}")

    search_results = st.session_state.get("kb_search_results")
    if search_results:
        st.caption(f"{len(search_results)} result(s)")
        for doc in search_results:
            with st.container(border=True):
                st.markdown(f"**{doc.get('id')}** &nbsp;|&nbsp; score: `{doc.get('score'):.3f}`")
                st.write(doc.get("text", "")[:400] + ("..." if len(doc.get("text", "")) > 400 else ""))
                with st.expander("Metadata"):
                    st.json(doc.get("metadata", {}))
                if st.button("🗑️ Delete this document", key=f"delete_doc_{doc.get('id')}"):
                    try:
                        del_result = _delete_json(base_url, f"/kb/documents/{doc.get('id')}")
                        st.success(f"Deleted {doc.get('id')}")
                        st.session_state["kb_search_results"] = [
                            d for d in search_results if d.get("id") != doc.get("id")
                        ]
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Delete failed: {exc}")
    elif search_results is not None:
        st.info("No matching documents.")

    st.divider()
    st.caption("Already know the document ID? Delete it directly:")
    col_did, col_dbtn = st.columns([3, 1])
    with col_did:
        direct_delete_id = st.text_input("Document ID", key="direct_delete_id", label_visibility="collapsed", placeholder="e.g. resolved-TCK-1042")
    with col_dbtn:
        if st.button("🗑️ Delete by ID"):
            if direct_delete_id.strip():
                try:
                    del_result = _delete_json(base_url, f"/kb/documents/{direct_delete_id.strip()}")
                    st.success(f"Deleted {direct_delete_id.strip()}")
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")
            else:
                st.warning("Enter a document ID first.")

with tabs[3]:
    # st.subheader("Resolved Ticket Registry")
    # st.write("Successful resolutions are ingested into the KB and stored in the resolved ticket log.")
    #
    # resolved_log_choice = st.selectbox("Resolved ticket log", ["resolved_tickets.log", "agent_loop_audit.log", "shadow_predictions.log"], key="resolved_log_choice")
    # resolved_lines_limit = st.slider("Lines", min_value=20, max_value=500, value=100, step=20, key="resolved_lines_limit")
    # if st.button("Refresh Resolved Tickets", key="refresh_resolved_tickets"):
    #     lines = _read_last_log_lines(repo_root, resolved_log_choice, resolved_lines_limit)
    #     if not lines:
    #         st.info("No resolved ticket records found yet.")
    #     else:
    #         st.code("".join(lines), language="json")
    #
    # st.divider()
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
    st.subheader("Log Explorer")
    st.caption("Search and filter across all three log files instead of scrolling raw dumps.")

    col_log, col_scan = st.columns([2, 1])
    with col_log:
        explorer_log_choice = st.selectbox(
            "Log source", ["All logs (merged)"] + ALL_LOG_FILES, key="explorer_log_choice"
        )
    with col_scan:
        scan_depth = st.number_input(
            "Lines to scan per file (most recent)", min_value=100, max_value=20000, value=2000, step=100,
            key="explorer_scan_depth",
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        explorer_ticket_id = st.text_input("Ticket ID contains", key="explorer_ticket_id")
    with col2:
        explorer_search = st.text_input("Free-text search (any field)", key="explorer_search")
    with col3:
        explorer_classifier = st.multiselect(
            "Classifier mode",
            ["llm", "heuristic_no_api_key", "heuristic_llm_call_failed", "heuristic_mock_mode", "unknown"],
            key="explorer_classifier_filter",
        )

    col4, col5, col6 = st.columns(3)
    with col4:
        explorer_actions = st.multiselect(
            "Action (agent_loop_audit.log only)",
            ["auto_route", "auto_resolve", "auto_route_spotcheck", "force_security_route", "human_review"],
            key="explorer_actions_filter",
        )
    with col5:
        use_date_filter = st.checkbox("Filter by date range", key="explorer_use_date")
    with col6:
        sort_order = st.selectbox("Sort", ["Newest first", "Oldest first"], key="explorer_sort_order")

    start_dt = end_dt = None
    if use_date_filter:
        col_from, col_to = st.columns(2)
        with col_from:
            from_date = st.date_input(
                "From", value=(datetime.now(timezone.utc) - timedelta(days=7)).date(), key="explorer_from_date"
            )
        with col_to:
            to_date = st.date_input("To", value=datetime.now(timezone.utc).date(), key="explorer_to_date")
        start_dt = datetime.combine(from_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(to_date, datetime.max.time(), tzinfo=timezone.utc)

    if st.button("🔍 Search Logs", key="explorer_search_btn"):
        if explorer_log_choice == "All logs (merged)":
            all_entries: List[Dict[str, Any]] = []
            for fname in ALL_LOG_FILES:
                all_entries.extend(_load_log_entries(repo_root, fname, int(scan_depth)))
        else:
            all_entries = _load_log_entries(repo_root, explorer_log_choice, int(scan_depth))

        filtered = _filter_log_entries(
            all_entries,
            search_text=explorer_search,
            classifier_modes=explorer_classifier,
            actions=explorer_actions,
            ticket_id=explorer_ticket_id,
            start_dt=start_dt,
            end_dt=end_dt,
        )
        filtered.sort(key=lambda e: e.get("timestamp", ""), reverse=(sort_order == "Newest first"))
        st.session_state["explorer_results"] = filtered
        st.session_state["explorer_scanned_count"] = len(all_entries)

    filtered = st.session_state.get("explorer_results")
    if filtered is not None:
        scanned = st.session_state.get("explorer_scanned_count", 0)
        st.caption(f"{len(filtered)} of {scanned} scanned entries match the current filters.")
        if not filtered:
            st.info("No matching log entries. Try widening the filters or increasing the scan depth.")
        else:
            table_rows = [
                {
                    "timestamp": e.get("timestamp", ""),
                    "ticket_id": e.get("ticket_id_source", ""),
                    "action / category": e.get("action") or e.get("category") or "",
                    "classifier_mode": e.get("classifier_mode_used", ""),
                    "log_file": e.get("_source_log", ""),
                }
                for e in filtered
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
            with st.expander(f"Raw matching entries ({len(filtered)})"):
                st.code(json.dumps(filtered, indent=2), language="json")
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


AUDIT_DB_PATH = Path(__file__).resolve().parents[3] / "triage_audit.db"


def _audit_dsn() -> Optional[str]:
    return os.getenv("AUDIT_DB_DSN")


def _sqlite_connect(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> bool:
    dsn = _audit_dsn()
    if not dsn:
        return False

    if dsn.startswith("sqlite://"):
        db_path = dsn.replace("sqlite:///", "", 1)
        if not db_path or db_path == ":memory:":
            db_path = str(AUDIT_DB_PATH)
        db_path = db_path if Path(db_path).is_absolute() else str((Path(__file__).resolve().parents[3] / db_path))
        with _sqlite_connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    ticket_id_source TEXT,
                    requester_identifier TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS resolved_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id_source TEXT NOT NULL,
                    requester_identifier TEXT,
                    subject TEXT,
                    category TEXT,
                    queue TEXT,
                    priority TEXT,
                    resolution_summary TEXT,
                    source_channel TEXT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
        return True

    if psycopg is None:
        raise RuntimeError("psycopg is required when using a Postgres audit database.")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    ticket_id_source TEXT,
                    requester_identifier TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    payload JSONB NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS resolved_tickets (
                    id SERIAL PRIMARY KEY,
                    ticket_id_source TEXT NOT NULL,
                    requester_identifier TEXT,
                    subject TEXT,
                    category TEXT,
                    queue TEXT,
                    priority TEXT,
                    resolution_summary TEXT,
                    source_channel TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    payload JSONB NOT NULL
                )
                """
            )
        conn.commit()
    return True


def initialize_audit_store() -> Dict[str, Any]:
    if not _audit_dsn():
        return {"status": "disabled", "reason": "AUDIT_DB_DSN not configured"}
    _ensure_schema()
    return {"status": "initialized", "dsn": _audit_dsn()}


def record_audit_event(event_type: str, payload: Dict[str, Any], ticket_id_source: Optional[str] = None, requester_identifier: Optional[str] = None) -> Dict[str, Any]:
    dsn = _audit_dsn()
    if not dsn:
        return {"status": "skipped", "reason": "AUDIT_DB_DSN not configured"}

    entry = {
        "event_type": event_type,
        "ticket_id_source": ticket_id_source,
        "requester_identifier": requester_identifier,
        "created_at": datetime.utcnow().isoformat(),
        **payload,
    }

    if dsn.startswith("sqlite://"):
        db_path = dsn.replace("sqlite:///", "", 1)
        if not db_path or db_path == ":memory:":
            db_path = str(AUDIT_DB_PATH)
        db_path = db_path if Path(db_path).is_absolute() else str((Path(__file__).resolve().parents[3] / db_path))
        with _sqlite_connect(db_path) as conn:
            conn.execute(
                "INSERT INTO audit_events (event_type, ticket_id_source, requester_identifier, created_at, payload) VALUES (?, ?, ?, ?, ?)",
                (event_type, ticket_id_source, requester_identifier, entry["created_at"], json.dumps(payload, default=str)),
            )
        return {"status": "recorded", "event_type": event_type}

    if psycopg is None:
        raise RuntimeError("psycopg is required when using a Postgres audit database.")

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_events (event_type, ticket_id_source, requester_identifier, created_at, payload) VALUES (%s, %s, %s, NOW(), %s)",
                    (event_type, ticket_id_source, requester_identifier, json.dumps(payload, default=str)),
                )
            conn.commit()
        return {"status": "recorded", "event_type": event_type}
    except Exception as exc:
        return {"status": "error", "event_type": event_type, "error": str(exc)}


def record_resolved_ticket(ticket: Dict[str, Any], resolution_summary: str, category: str, queue: str, priority: str, source_channel: str = "web_form") -> Dict[str, Any]:
    dsn = _audit_dsn()
    if not dsn:
        return {"status": "skipped", "reason": "AUDIT_DB_DSN not configured"}

    payload = {
        "ticket_id_source": ticket.get("ticket_id_source"),
        "requester_identifier": ticket.get("requester_identifier"),
        "subject": ticket.get("subject"),
        "body_raw": ticket.get("body_raw"),
        "source_channel": source_channel,
        "resolution_summary": resolution_summary,
        "category": category,
        "queue": queue,
        "priority": priority,
        "created_at": datetime.utcnow().isoformat(),
    }

    if dsn.startswith("sqlite://"):
        db_path = dsn.replace("sqlite:///", "", 1)
        if not db_path or db_path == ":memory:":
            db_path = str(AUDIT_DB_PATH)
        db_path = db_path if Path(db_path).is_absolute() else str((Path(__file__).resolve().parents[3] / db_path))
        with _sqlite_connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO resolved_tickets (ticket_id_source, requester_identifier, subject, category, queue, priority, resolution_summary, source_channel, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket.get("ticket_id_source"),
                    ticket.get("requester_identifier"),
                    ticket.get("subject"),
                    category,
                    queue,
                    priority,
                    resolution_summary,
                    source_channel,
                    payload["created_at"],
                    json.dumps(payload, default=str),
                ),
            )
        return {"status": "recorded", "ticket_id_source": ticket.get("ticket_id_source")}

    if psycopg is None:
        raise RuntimeError("psycopg is required when using a Postgres audit database.")

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO resolved_tickets (ticket_id_source, requester_identifier, subject, category, queue, priority, resolution_summary, source_channel, created_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
                    """,
                    (
                        ticket.get("ticket_id_source"),
                        ticket.get("requester_identifier"),
                        ticket.get("subject"),
                        category,
                        queue,
                        priority,
                        resolution_summary,
                        source_channel,
                        json.dumps(payload, default=str),
                    ),
                )
            conn.commit()
        return {"status": "recorded", "ticket_id_source": ticket.get("ticket_id_source")}
    except Exception as exc:
        return {"status": "error", "ticket_id_source": ticket.get("ticket_id_source"), "error": str(exc)}


def list_recent_resolved_tickets(limit: int = 20) -> List[Dict[str, Any]]:
    dsn = _audit_dsn()
    if not dsn:
        return []

    if dsn.startswith("sqlite://"):
        db_path = dsn.replace("sqlite:///", "", 1)
        if not db_path or db_path == ":memory:":
            db_path = str(AUDIT_DB_PATH)
        db_path = db_path if Path(db_path).is_absolute() else str((Path(__file__).resolve().parents[3] / db_path))
        with _sqlite_connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM resolved_tickets ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    if psycopg is None:
        raise RuntimeError("psycopg is required when using a Postgres audit database.")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM resolved_tickets ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
    columns = ["id", "ticket_id_source", "requester_identifier", "subject", "category", "queue", "priority", "resolution_summary", "source_channel", "created_at", "payload"]
    return [dict(zip(columns, row)) for row in rows]

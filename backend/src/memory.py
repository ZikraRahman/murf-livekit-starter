"""SQLite-backed, privacy-conscious memory for Bharat Finance Assistant."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "memory.db"
MemoryFactValue = str | bool | int | float | None


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                language_preference TEXT,
                facts TEXT NOT NULL DEFAULT '{}',
                last_interaction TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS escalation_requests (
                reference_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                who_needs_help TEXT NOT NULL,
                what_happened TEXT NOT NULL,
                what_agent_checked TEXT NOT NULL,
                urgency TEXT NOT NULL,
                caller_language TEXT NOT NULL,
                preferred_follow_up TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS call_records (
                call_id TEXT PRIMARY KEY,
                user_id TEXT,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def record_call(
    *, call_id: str, user_id: str | None, outcome: str
) -> bool:
    """Record one completed call. Duplicate lifecycle events are ignored."""
    if outcome not in {"success", "failed"}:
        raise ValueError("Call outcome must be 'success' or 'failed'.")
    init_db()
    with _connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO call_records (call_id, user_id, outcome, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (call_id, user_id, outcome, datetime.now(timezone.utc).isoformat()),
        )
    return cursor.rowcount > 0


def get_call_analytics() -> dict[str, int]:
    """Return aggregate, non-sensitive call outcomes for the dashboard."""
    init_db()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_calls,
                COALESCE(SUM(outcome = 'success'), 0) AS successful_calls,
                COALESCE(SUM(outcome = 'failed'), 0) AS failed_calls
            FROM call_records
            """
        ).fetchone()
    return {
        "total_calls": int(row["total_calls"]),
        "successful_calls": int(row["successful_calls"]),
        "failed_calls": int(row["failed_calls"]),
    }


def _safe_facts(value: str | None) -> dict[str, MemoryFactValue]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        str(key): item
        for key, item in parsed.items()
        if item is None or isinstance(item, (str, bool, int, float))
    }


def get_user(user_id: str) -> dict[str, Any] | None:
    init_db()
    with _connection() as connection:
        row = connection.execute(
            "SELECT user_id, name, language_preference, facts, last_interaction "
            "FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "name": row["name"],
        "language_preference": row["language_preference"],
        "facts": _safe_facts(row["facts"]),
        "last_interaction": row["last_interaction"],
    }


def upsert_user(
    user_id: str,
    *,
    name: str | None = None,
    language_preference: str | None = None,
    facts: dict[str, MemoryFactValue] | None = None,
) -> dict[str, Any]:
    """Merge safe fields into a caller record and return the resulting memory."""
    existing = get_user(user_id) or {}
    merged_facts = {**existing.get("facts", {}), **(facts or {})}
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, name, language_preference, facts, last_interaction)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name,
                language_preference = excluded.language_preference,
                facts = excluded.facts,
                last_interaction = excluded.last_interaction
            """,
            (
                user_id,
                name if name is not None else existing.get("name"),
                language_preference
                if language_preference is not None
                else existing.get("language_preference"),
                json.dumps(merged_facts),
                timestamp,
            ),
        )
    return get_user(user_id) or {}


def delete_user(user_id: str) -> bool:
    init_db()
    with _connection() as connection:
        cursor = connection.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    return cursor.rowcount > 0


def delete_memory_fact(user_id: str, key: str) -> bool:
    """Delete a top-level field or one fact. Remove an empty record entirely."""
    user = get_user(user_id)
    if user is None:
        return False
    if key in {"name", "language_preference"}:
        with _connection() as connection:
            connection.execute(
                f"UPDATE users SET {key} = NULL, last_interaction = ? WHERE user_id = ?",
                (datetime.now(timezone.utc).isoformat(), user_id),
            )
        return True
    facts = user["facts"]
    if key not in facts:
        return False
    del facts[key]
    with _connection() as connection:
        connection.execute(
            "UPDATE users SET facts = ?, last_interaction = ? WHERE user_id = ?",
            (json.dumps(facts), datetime.now(timezone.utc).isoformat(), user_id),
        )
    return True


def create_escalation_request(
    *,
    user_id: str,
    who_needs_help: str,
    what_happened: str,
    what_agent_checked: str,
    urgency: str,
    caller_language: str,
    preferred_follow_up: str,
) -> dict[str, str]:
    """Persist a human-review request and return its unique reference ID."""
    init_db()
    reference_id = (
        f"ESC-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    )
    created_at = datetime.now(timezone.utc).isoformat()
    request = {
        "reference_id": reference_id,
        "user_id": user_id,
        "who_needs_help": who_needs_help,
        "what_happened": what_happened,
        "what_agent_checked": what_agent_checked,
        "urgency": urgency,
        "caller_language": caller_language,
        "preferred_follow_up": preferred_follow_up,
        "status": "open",
        "created_at": created_at,
    }
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO escalation_requests (
                reference_id, user_id, who_needs_help, what_happened,
                what_agent_checked, urgency, caller_language,
                preferred_follow_up, status, created_at
            ) VALUES (
                :reference_id, :user_id, :who_needs_help, :what_happened,
                :what_agent_checked, :urgency, :caller_language,
                :preferred_follow_up, :status, :created_at
            )
            """,
            request,
        )
    return request


def get_escalation_request(reference_id: str) -> dict[str, str] | None:
    """Return one persisted escalation for a human reviewer."""
    init_db()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT reference_id, user_id, who_needs_help, what_happened,
                   what_agent_checked, urgency, caller_language,
                   preferred_follow_up, status, created_at
            FROM escalation_requests WHERE reference_id = ?
            """,
            (reference_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def list_escalation_requests(status: str = "open") -> list[dict[str, str]]:
    """Return persisted escalation requests for the human-review dashboard."""
    init_db()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT reference_id, who_needs_help, what_happened,
                   what_agent_checked, urgency, caller_language,
                   preferred_follow_up, status, created_at
            FROM escalation_requests
            WHERE status = ?
            ORDER BY created_at DESC
            """,
            (status,),
        ).fetchall()
    return [dict(row) for row in rows]

"""SQLite-backed, privacy-conscious memory for Bharat Finance Assistant."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "memory.db"


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


def _safe_facts(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(item) for key, item in parsed.items()}


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
    facts: dict[str, str] | None = None,
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

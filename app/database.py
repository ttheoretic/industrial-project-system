"""SQLite persistence (CRM-light). One row per offer, JSON columns for AI output."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'draft',
    source TEXT NOT NULL DEFAULT 'manual',
    raw_inquiry TEXT NOT NULL,
    customer_email TEXT,
    email_from TEXT,
    email_subject TEXT,
    attachments_json TEXT NOT NULL DEFAULT '[]',
    analysis_json TEXT NOT NULL,
    costing_json TEXT NOT NULL,
    risks_json TEXT NOT NULL,
    final_price REAL,
    offer_html TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Spalten, die per Migration zu bestehenden Datenbanken hinzugefügt werden
_MIGRATIONS = [
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("email_from", "TEXT"),
    ("email_subject", "TEXT"),
    ("attachments_json", "TEXT NOT NULL DEFAULT '[]'"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(offers)")}
        for column, ddl in _MIGRATIONS:
            if column not in existing:
                conn.execute(f"ALTER TABLE offers ADD COLUMN {column} {ddl}")


def create_offer(
    raw_inquiry: str,
    customer_email: Optional[str],
    analysis: dict,
    costing: dict,
    risks: dict,
    source: str = "manual",
    email_from: Optional[str] = None,
    email_subject: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
) -> int:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO offers
               (status, source, raw_inquiry, customer_email, email_from, email_subject,
                attachments_json, analysis_json, costing_json, risks_json,
                created_at, updated_at)
               VALUES ('draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source,
                raw_inquiry,
                customer_email,
                email_from,
                email_subject,
                json.dumps(attachments or []),
                json.dumps(analysis),
                json.dumps(costing),
                json.dumps(risks),
                now,
                now,
            ),
        )
        return cur.lastrowid


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "source": row["source"],
        "raw_inquiry": row["raw_inquiry"],
        "customer_email": row["customer_email"],
        "email_from": row["email_from"],
        "email_subject": row["email_subject"],
        "attachments": json.loads(row["attachments_json"]),
        "analysis": json.loads(row["analysis_json"]),
        "costing": json.loads(row["costing_json"]),
        "risks": json.loads(row["risks_json"]),
        "final_price": row["final_price"],
        "offer_html": row["offer_html"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_offer(offer_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_offers() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM offers ORDER BY created_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def update_offer(offer_id: int, **fields: Any) -> None:
    """Update selected columns. Dict values are JSON-encoded into *_json columns."""
    column_map = {
        "analysis": "analysis_json",
        "costing": "costing_json",
        "risks": "risks_json",
    }
    sets, values = [], []
    for key, value in fields.items():
        column = column_map.get(key, key)
        if column.endswith("_json"):
            value = json.dumps(value)
        sets.append(f"{column} = ?")
        values.append(value)
    sets.append("updated_at = ?")
    values.append(_now())
    values.append(offer_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE offers SET {', '.join(sets)} WHERE id = ?", values)

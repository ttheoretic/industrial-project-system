"""SQLite-Persistenz für die gesamte Plattform.

Das Angebots-/Quotation-Modul (`offers`) bleibt die Grundlage; alle weiteren
Module (CRM, Pipeline, Projekte, Material, Produktion, Zeiterfassung, Dokumente,
Aktivitäten) hängen relational daran. Generische CRUD-Helfer halten die
einzelnen Modul-Funktionen schlank.
"""

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
    company_id INTEGER,
    contact_id INTEGER,
    pipeline_stage TEXT NOT NULL DEFAULT 'draft',
    valid_until TEXT,
    last_customer_reply_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    address TEXT,
    industry TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    role TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER,
    company_id INTEGER,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    responsible TEXT,
    order_value REAL,
    deadline TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    assignee TEXT,
    planned_hours REAL DEFAULT 0,
    is_milestone INTEGER NOT NULL DEFAULT 0,
    due_date TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    spec TEXT,
    quantity REAL DEFAULT 1,
    unit TEXT DEFAULT 'Stk',
    supplier TEXT,
    unit_cost REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'needed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    work_center TEXT,
    capacity_hours_per_week REAL DEFAULT 40,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS production_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id INTEGER NOT NULL,
    project_id INTEGER,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    hours REAL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    task_id INTEGER,
    employee TEXT NOT NULL,
    hours REAL NOT NULL,
    hourly_rate REAL,
    entry_date TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT,
    path TEXT NOT NULL,
    media_type TEXT,
    size_bytes INTEGER,
    version INTEGER NOT NULL DEFAULT 1,
    company_id INTEGER,
    project_id INTEGER,
    offer_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'note',
    body TEXT NOT NULL,
    meta_json TEXT NOT NULL DEFAULT '{}',
    author TEXT DEFAULT 'system',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS material_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    eur_per_kg REAL NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

# Spalten, die per Migration zu bestehenden offers-Tabellen ergänzt werden
_OFFER_MIGRATIONS = [
    ("source", "TEXT NOT NULL DEFAULT 'manual'"),
    ("email_from", "TEXT"),
    ("email_subject", "TEXT"),
    ("attachments_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("company_id", "INTEGER"),
    ("contact_id", "INTEGER"),
    ("pipeline_stage", "TEXT NOT NULL DEFAULT 'draft'"),
    ("valid_until", "TEXT"),
    ("last_customer_reply_at", "TEXT"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(offers)")}
        for column, ddl in _OFFER_MIGRATIONS:
            if column not in existing:
                conn.execute(f"ALTER TABLE offers ADD COLUMN {column} {ddl}")
        # pipeline_stage für Altbestände aus dem internen Status ableiten
        conn.execute(
            "UPDATE offers SET pipeline_stage = CASE status "
            "WHEN 'draft' THEN 'draft' WHEN 'reviewed' THEN 'internal_review' "
            "WHEN 'sent' THEN 'sent' WHEN 'accepted' THEN 'won' "
            "WHEN 'rejected' THEN 'lost' ELSE pipeline_stage END "
            "WHERE pipeline_stage = 'draft' AND status != 'draft'"
        )


# ---------------------------------------------------------------------------
# Generische CRUD-Helfer
# ---------------------------------------------------------------------------

_JSON_COLUMNS = {"attachments", "analysis", "costing", "risks", "meta"}


def _encode(key: str, value: Any) -> tuple[str, Any]:
    """Mappt Logiknamen auf Spalten und JSON-codiert komplexe Werte."""
    if key in _JSON_COLUMNS:
        return f"{key}_json", json.dumps(value)
    return key, value


def insert(table: str, **fields: Any) -> int:
    fields.setdefault("created_at", _now())
    cols, vals = [], []
    for key, value in fields.items():
        col, val = _encode(key, value)
        cols.append(col)
        vals.append(val)
    placeholders = ", ".join("?" for _ in cols)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        return cur.lastrowid


def update(table: str, row_id: int, **fields: Any) -> None:
    if not fields:
        return
    sets, vals = [], []
    for key, value in fields.items():
        col, val = _encode(key, value)
        sets.append(f"{col} = ?")
        vals.append(val)
    if _has_column(table, "updated_at"):
        sets.append("updated_at = ?")
        vals.append(_now())
    vals.append(row_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", vals)


def delete(table: str, row_id: int) -> None:
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def _has_column(table: str, column: str) -> bool:
    with get_conn() as conn:
        return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def fetch_one(table: str, row_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def fetch_all(
    table: str, where: str = "", params: tuple = (), order: str = "id DESC"
) -> list[dict]:
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Read-only Abfrage für Analytics/Copilot. Liefert Liste von Dicts."""
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ---------------------------------------------------------------------------
# Angebote (Quotation-Kern — unveränderte Signaturen)
# ---------------------------------------------------------------------------


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
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
) -> int:
    now = _now()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO offers
               (status, pipeline_stage, source, raw_inquiry, customer_email,
                email_from, email_subject, attachments_json, analysis_json,
                costing_json, risks_json, company_id, contact_id, created_at, updated_at)
               VALUES ('draft', 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                company_id,
                contact_id,
                now,
                now,
            ),
        )
        return cur.lastrowid


def _offer_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "pipeline_stage": row["pipeline_stage"],
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
        "company_id": row["company_id"],
        "contact_id": row["contact_id"],
        "valid_until": row["valid_until"],
        "last_customer_reply_at": row["last_customer_reply_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_offer(offer_id: int) -> Optional[dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    return _offer_row_to_dict(row) if row else None


def list_offers(where: str = "", params: tuple = ()) -> list[dict[str, Any]]:
    sql = "SELECT * FROM offers"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        return [_offer_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def update_offer(offer_id: int, **fields: Any) -> None:
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


# ---------------------------------------------------------------------------
# Aktivitäten / Timeline (modulübergreifend)
# ---------------------------------------------------------------------------


def add_activity(
    entity_type: str,
    entity_id: int,
    body: str,
    kind: str = "note",
    author: str = "user",
    meta: Optional[dict] = None,
) -> int:
    return insert(
        "activities",
        entity_type=entity_type,
        entity_id=entity_id,
        kind=kind,
        body=body,
        author=author,
        meta=meta or {},
    )


def list_activities(entity_type: str, entity_id: int) -> list[dict]:
    rows = fetch_all(
        "activities",
        "entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
        order="created_at DESC",
    )
    for r in rows:
        r["meta"] = json.loads(r.pop("meta_json", "{}"))
    return rows

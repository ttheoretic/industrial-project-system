"""Unternehmens-Stammdaten & Pauschalen (alles, was je Unternehmen unterschiedlich ist).

Wird als ein JSON-Dokument in der Tabelle `settings` (eine Zeile) gehalten und
mit Defaults aus config.py zusammengeführt. Kalkulation und Angebotsdokument
lesen ihre Parameter von hier — so kann jedes Unternehmen eigene Werte pflegen,
ohne Code zu ändern.
"""

import copy
import json
import sqlite3

from . import config, database


def _safe_fetch(table: str, where: str = "", params: tuple = (), order: str = "id DESC") -> list:
    """Wie database.fetch_all, aber tolerant, falls die Tabelle (noch) fehlt
    (z. B. in Unit-Tests ohne init_db)."""
    try:
        return database.fetch_all(table, where, params, order)
    except sqlite3.OperationalError:
        return []

DEFAULTS: dict = {
    "company": {
        "name": "",
        "address": "",
        "email": "",
        "phone": "",
        "vat_id": "",
        "website": "",
        "logo_data_url": "",
    },
    "pricing": {
        "hourly_rate": config.HOURLY_PRODUCTION_RATE_EUR,
        "overhead_pct": config.OVERHEAD_PERCENT,
        "target_margin_pct": config.TARGET_MARGIN_PERCENT,
        "setup_cost": config.SETUP_COST_EUR_PER_PART_TYPE,
        "complexity": dict(config.COMPLEXITY_FACTORS),
    },
    "commercial": {
        "currency": "EUR",
        "vat_rate": 0.19,
        "payment_terms": "30 Tage netto",
        "validity_days": 30,
        "terms_text": (
            "Es gelten unsere Allgemeinen Geschäftsbedingungen. Lieferung ab Werk "
            "(EXW). Eigentumsvorbehalt bis zur vollständigen Bezahlung."
        ),
    },
    "ai": {
        # Modell für Analyse/Risiko/Angebotstext/Copilot. Günstig = Haiku.
        "model": config.ANTHROPIC_MODEL,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def get_settings() -> dict:
    rows = _safe_fetch("settings", "id = 1")
    stored = json.loads(rows[0]["data"]) if rows else {}
    return _deep_merge(DEFAULTS, stored)


def update_settings(patch: dict) -> dict:
    current = get_settings()
    merged = _deep_merge(current, patch)
    # nur die Abweichungen gegenüber DEFAULTS speichern wäre möglich; wir
    # speichern das vollständige Dokument für Einfachheit/Robustheit.
    rows = _safe_fetch("settings", "id = 1")
    payload = json.dumps(merged)
    with database.get_conn() as conn:
        if rows:
            conn.execute("UPDATE settings SET data = ? WHERE id = 1", (payload,))
        else:
            conn.execute("INSERT INTO settings (id, data) VALUES (1, ?)", (payload,))
    return merged


# ---------------------------------------------------------------------------
# Effektive Kalkulationsparameter (für costing.py)
# ---------------------------------------------------------------------------


def pricing() -> dict:
    return get_settings()["pricing"]


def ai_model() -> str:
    """Konfiguriertes KI-Modell (Einstellungen), Fallback auf config."""
    try:
        return get_settings()["ai"]["model"] or config.ANTHROPIC_MODEL
    except (KeyError, TypeError):
        return config.ANTHROPIC_MODEL


def material_rate(material: str) -> float:
    """EUR/kg aus der pflegbaren Materialpreisliste; Fallback auf config-Tabelle."""
    key = material.strip().lower()
    rows = _safe_fetch("material_prices")
    by_name = {r["name"].strip().lower(): r["eur_per_kg"] for r in rows}
    if key in by_name:
        return by_name[key]
    for name, rate in by_name.items():
        if name in key or key in name:
            return rate
    return config.material_rate(material)


def list_material_prices() -> list[dict]:
    return _safe_fetch("material_prices", order="name")


def seed_material_prices_if_empty() -> None:
    """Beim ersten Start die config-Materialtabelle in die pflegbare Liste übernehmen."""
    if database.fetch_all("material_prices"):
        return
    for name, rate in config.MATERIAL_COSTS_EUR_PER_KG.items():
        database.insert("material_prices", name=name, eur_per_kg=rate)

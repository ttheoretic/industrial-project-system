"""Modulübergreifende Geschäftslogik: Auftragswandlung, Nachkalkulation, Analytics.

Alle Zahlen stammen aus echten Datensätzen (Angebote, Zeiterfassung, Material).
Es werden keine Werte erfunden — fehlende Daten erscheinen als 0 bzw. werden
ausgewiesen.
"""

from datetime import datetime, timezone
from typing import Optional

from . import config, database

PROJECT_STATUSES = ["planned", "in_progress", "waiting", "completed", "delivered"]
PIPELINE_STAGES = [
    "draft",
    "internal_review",
    "sent",
    "viewed",
    "negotiation",
    "won",
    "lost",
]


def _offer_value(offer: dict) -> float:
    return offer.get("final_price") or offer["costing"].get("recommended_price", 0.0)


# ---------------------------------------------------------------------------
# Modul 4: Auftragswandlung — aus gewonnenem Angebot Projekt + Auftrag erzeugen
# ---------------------------------------------------------------------------


def convert_offer_to_project(offer_id: int) -> dict:
    """Markiert ein Angebot als gewonnen und legt ohne Doppelerfassung ein Projekt
    inkl. Material- und Aufgaben-Vorbelegung aus der Angebotsanalyse an."""
    offer = database.get_offer(offer_id)
    if offer is None:
        raise ValueError("Angebot nicht gefunden")

    existing = database.fetch_all("projects", "offer_id = ?", (offer_id,))
    if existing:
        return existing[0]  # bereits gewandelt — keine Dublette

    analysis = offer["analysis"]
    customer = analysis.get("customer_name") or offer.get("email_from") or "Kunde"
    value = _offer_value(offer)

    project_id = database.insert(
        "projects",
        offer_id=offer_id,
        company_id=offer.get("company_id"),
        name=f"Auftrag {customer} (Angebot #{offer_id})",
        status="planned",
        order_value=value,
        deadline=analysis.get("deadline"),
        notes="Automatisch aus gewonnenem Angebot erzeugt.",
        updated_at=database._now(),
    )

    # Positionen → Aufgaben + Materialbedarf vorbelegen (aus echter Analyse)
    for part in analysis.get("parts", []):
        database.insert(
            "tasks",
            project_id=project_id,
            title=f"Fertigung: {part['name']} (×{part.get('quantity', 1)})",
            status="open",
            planned_hours=part.get("estimated_machining_hours_per_part", 0)
            * part.get("quantity", 1),
        )
        database.insert(
            "materials",
            project_id=project_id,
            name=part.get("material", "—"),
            spec=part.get("name"),
            quantity=part.get("estimated_mass_kg_per_part", 0) * part.get("quantity", 1),
            unit="kg",
            status="needed",
        )

    database.update_offer(offer_id, status="accepted", pipeline_stage="won")
    database.add_activity(
        "offer", offer_id, f"Angebot gewonnen → Projekt #{project_id} erstellt.",
        kind="status", author="system",
    )
    database.add_activity(
        "project", project_id, "Projekt aus Angebot erzeugt (keine Doppelerfassung).",
        kind="status", author="system",
    )
    return database.fetch_one("projects", project_id)


# ---------------------------------------------------------------------------
# Modul 9: Nachkalkulation — Soll (Angebot) vs. Ist (Zeit + Material)
# ---------------------------------------------------------------------------


def post_calculation(project_id: int) -> dict:
    """Vergleicht geschätzte Kosten (aus dem Angebot) mit Ist-Kosten (erfasste
    Stunden + Materialstatus). Jede Zahl ist auf reale Datensätze zurückführbar."""
    project = database.fetch_one("projects", project_id)
    if project is None:
        raise ValueError("Projekt nicht gefunden")

    offer = database.get_offer(project["offer_id"]) if project["offer_id"] else None
    costing = offer["costing"] if offer else {}

    est_material = sum(p.get("material_cost", 0) for p in costing.get("parts", []))
    est_labor = sum(p.get("labor_cost", 0) for p in costing.get("parts", []))
    est_total = costing.get("total_cost", est_material + est_labor)
    est_price = _offer_value(offer) if offer else 0.0

    # Ist-Arbeit aus Zeiterfassung
    time_entries = database.fetch_all("time_entries", "project_id = ?", (project_id,))
    actual_hours = sum(t["hours"] for t in time_entries)
    actual_labor = sum(
        t["hours"] * (t["hourly_rate"] or config.HOURLY_PRODUCTION_RATE_EUR)
        for t in time_entries
    )

    # Ist-Material aus Materialliste (bestellt/erhalten zählt als angefallen)
    materials = database.fetch_all("materials", "project_id = ?", (project_id,))
    actual_material = sum(
        (m["unit_cost"] or 0) * (m["quantity"] or 0)
        for m in materials
        if m["status"] in ("ordered", "received")
    )

    actual_total = actual_labor + actual_material
    planned_hours = sum(t["planned_hours"] or 0 for t in
                        database.fetch_all("tasks", "project_id = ?", (project_id,)))

    def variance(estimate: float, actual: float) -> dict:
        return {
            "estimate": round(estimate, 2),
            "actual": round(actual, 2),
            "variance": round(actual - estimate, 2),
            "variance_pct": round((actual - estimate) / estimate * 100, 1)
            if estimate else None,
        }

    est_margin = est_price - est_total
    actual_margin = est_price - actual_total  # Verkaufspreis ist fix nach Auftrag

    return {
        "project_id": project_id,
        "has_offer": offer is not None,
        "selling_price": round(est_price, 2),
        "material": variance(est_material, actual_material),
        "labor": variance(est_labor, actual_labor),
        "total_cost": variance(est_total, actual_total),
        "hours": {"planned": round(planned_hours, 1), "actual": round(actual_hours, 1)},
        "margin": {
            "estimated": round(est_margin, 2),
            "actual": round(actual_margin, 2),
            "variance": round(actual_margin - est_margin, 2),
        },
        "data_completeness": {
            "time_entries": len(time_entries),
            "materials_costed": sum(1 for m in materials if (m["unit_cost"] or 0) > 0),
            "materials_total": len(materials),
        },
    }


# ---------------------------------------------------------------------------
# Modul 12: Analytics — Vertrieb, Betrieb, Profitabilität (aus echten Daten)
# ---------------------------------------------------------------------------


def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def analytics_overview() -> dict:
    offers = database.list_offers()
    projects = database.fetch_all("projects")

    won = [o for o in offers if o["pipeline_stage"] == "won"]
    lost = [o for o in offers if o["pipeline_stage"] == "lost"]
    decided = len(won) + len(lost)
    revenue = sum(_offer_value(o) for o in won)
    open_value = sum(
        _offer_value(o) for o in offers
        if o["pipeline_stage"] in ("sent", "viewed", "negotiation")
    )

    active = [p for p in projects if p["status"] in ("planned", "in_progress", "waiting")]
    delayed = []
    for p in active:
        d = _days_since(p["deadline"]) if p["deadline"] else None
        # Frist in der Vergangenheit (positive Tage seit Deadline) = überfällig
        if p["deadline"]:
            try:
                deadline = datetime.fromisoformat(p["deadline"])
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if deadline < datetime.now(timezone.utc):
                    delayed.append(p)
            except ValueError:
                pass

    # Maschinenauslastung: geplante Slot-Stunden vs. Kapazität
    machines = database.fetch_all("machines")
    slots = database.fetch_all("production_slots")
    total_capacity = sum(m["capacity_hours_per_week"] or 0 for m in machines)
    booked = sum(s["hours"] or 0 for s in slots)

    # Marge je Kunde (gewonnene Angebote, Soll-Marge)
    by_company: dict = {}
    companies = {c["id"]: c["name"] for c in database.fetch_all("companies")}
    for o in won:
        name = (
            companies.get(o["company_id"])
            or o["analysis"].get("customer_name")
            or o.get("email_from")
            or "Unbekannt"
        )
        entry = by_company.setdefault(name, {"revenue": 0.0, "margin": 0.0, "count": 0})
        entry["revenue"] += _offer_value(o)
        entry["margin"] += o["costing"].get("margin_eur", 0)
        entry["count"] += 1

    return {
        "sales": {
            "revenue_won": round(revenue, 2),
            "open_pipeline_value": round(open_value, 2),
            "won_count": len(won),
            "lost_count": len(lost),
            "conversion_rate": round(len(won) / decided * 100, 1) if decided else None,
            "total_offers": len(offers),
        },
        "operations": {
            "active_projects": len(active),
            "delayed_projects": len(delayed),
            "delayed_list": [
                {"id": p["id"], "name": p["name"], "deadline": p["deadline"]}
                for p in delayed
            ],
            "machine_utilization_pct": round(booked / total_capacity * 100, 1)
            if total_capacity else None,
        },
        "profitability": {
            "by_customer": sorted(
                [
                    {"customer": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv
                                       for kk, vv in v.items()}}
                    for k, v in by_company.items()
                ],
                key=lambda x: x["revenue"],
                reverse=True,
            ),
        },
    }

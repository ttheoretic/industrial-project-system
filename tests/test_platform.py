"""Tests für die Plattform-Module: Auftragswandlung, Nachkalkulation, Analytics,
Copilot-Werkzeuge, Follow-up-Erkennung — alle ohne API-Key (kein Modellaufruf)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import config, copilot, database, followup, services


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    database.init_db()
    yield


def _seed_offer(stage="draft", price=10000.0, severity=3, customer="ACME GmbH",
                material_cost=2000.0, labor_cost=5000.0, total=7000.0):
    analysis = {
        "customer_name": customer, "customer_contact": None, "parts": [
            {"name": "Halterung", "description": "x", "quantity": 10,
             "material": "Aluminum 6061", "material_is_assumption": False,
             "estimated_mass_kg_per_part": 0.5,
             "estimated_machining_hours_per_part": 2.0, "complexity": "medium",
             "technical_requirements": [], "confidence": 80}
        ],
        "deadline": None, "general_requirements": [], "missing_information": [],
        "assumptions": [], "overall_confidence": 80,
    }
    costing = {
        "parts": [{"part_name": "Halterung", "quantity": 10, "material": "Aluminum 6061",
                   "material_rate_eur_per_kg": 4.0, "material_cost": material_cost,
                   "machining_hours_total": 20.0, "complexity_factor": 1.3,
                   "labor_cost": labor_cost, "setup_cost": 150.0, "subtotal": total}],
        "direct_cost": total, "overhead_percent": 0.15, "overhead_cost": 0.0,
        "total_cost": total, "target_margin_percent": 0.30,
        "recommended_price": price, "margin_eur": price - total,
    }
    risks = {"risks": [{"category": "production_risk", "description": "x",
                        "severity": severity, "mitigation": "y"}],
             "overall_severity": severity, "summary": "s"}
    oid = database.create_offer("Anfrage", "a@acme.de", analysis, costing, risks)
    database.update_offer(oid, final_price=price, pipeline_stage=stage)
    return oid


def test_convert_offer_creates_project_tasks_materials():
    oid = _seed_offer()
    project = services.convert_offer_to_project(oid)
    assert project["offer_id"] == oid
    assert project["order_value"] == 10000.0
    tasks = database.fetch_all("tasks", "project_id = ?", (project["id"],))
    materials = database.fetch_all("materials", "project_id = ?", (project["id"],))
    assert len(tasks) == 1 and tasks[0]["planned_hours"] == 20.0
    assert len(materials) == 1
    # zweite Wandlung erzeugt keine Dublette
    again = services.convert_offer_to_project(oid)
    assert again["id"] == project["id"]
    assert database.get_offer(oid)["pipeline_stage"] == "won"


def test_post_calculation_variances():
    oid = _seed_offer(material_cost=2000.0, labor_cost=5000.0, total=7000.0, price=10000.0)
    project = services.convert_offer_to_project(oid)
    pid = project["id"]
    # Ist-Stunden: 60h à 95 € = 5700 € Arbeit (Schätzung war 5000)
    database.insert("time_entries", project_id=pid, employee="Max", hours=60.0,
                    hourly_rate=95.0, entry_date="2026-01-01")
    # Material bestellt mit Ist-Kosten 2500 (Schätzung 2000)
    mats = database.fetch_all("materials", "project_id = ?", (pid,))
    database.update("materials", mats[0]["id"], status="received", unit_cost=500.0, quantity=5)
    pc = services.post_calculation(pid)
    assert pc["labor"]["estimate"] == 5000.0
    assert pc["labor"]["actual"] == 5700.0
    assert pc["labor"]["variance"] == 700.0
    assert pc["material"]["actual"] == 2500.0
    assert pc["margin"]["estimated"] == 3000.0          # 10000 - 7000
    assert pc["margin"]["actual"] == 10000.0 - (5700.0 + 2500.0)


def test_analytics_conversion_and_revenue():
    _seed_offer(stage="won", price=10000.0, customer="ACME GmbH")
    _seed_offer(stage="won", price=5000.0, customer="ACME GmbH")
    _seed_offer(stage="lost", price=3000.0, customer="Beta AG")
    _seed_offer(stage="sent", price=8000.0, customer="Gamma KG")
    ov = services.analytics_overview()
    assert ov["sales"]["revenue_won"] == 15000.0
    assert ov["sales"]["won_count"] == 2
    assert ov["sales"]["lost_count"] == 1
    assert ov["sales"]["conversion_rate"] == round(2 / 3 * 100, 1)
    assert ov["sales"]["open_pipeline_value"] == 8000.0
    top = ov["profitability"]["by_customer"][0]
    assert top["customer"] == "ACME GmbH" and top["revenue"] == 15000.0


def test_copilot_tools_use_real_data_only():
    oid = _seed_offer(stage="sent", severity=5, customer="HighRisk GmbH")
    _seed_offer(stage="won", severity=2, customer="Safe AG")
    # höchstes Risiko korrekt identifiziert
    top = copilot._run_tool("highest_risk_offer", {})
    assert top["id"] == oid and top["risk_severity"] == 5
    # Filter nach Stage
    sent = copilot._run_tool("list_offers", {"pipeline_stage": "sent"})
    assert all(o["pipeline_stage"] == "sent" for o in sent)
    # Umsatz je Kunde stammt aus echten Datensätzen
    rev = copilot._run_tool("revenue_by_customer", {})
    assert any(c["customer"] == "Safe AG" for c in rev)


def test_followup_detects_idle_offer():
    oid = _seed_offer(stage="sent")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    database.update_offer(oid, last_customer_reply_at=old)
    suggestions = followup.detect_suggestions()
    match = [s for s in suggestions if s["offer_id"] == oid]
    assert match and match[0]["days_idle"] >= 7
    assert any("keine Reaktion" in r for r in match[0]["reasons"])


def test_followup_approval_flow():
    oid = _seed_offer(stage="sent")
    aid = database.add_activity("offer", oid, "Entwurf", kind="email_draft",
                                meta={"approved": False})
    result = followup.approve_followup(aid)
    assert result["approved"] is True
    activity = database.fetch_one("activities", aid)
    assert json.loads(activity["meta_json"])["approved"] is True


def test_settings_drive_costing():
    """Geänderte Stammdaten (Stundensatz/Marge) wirken sich auf die Kalkulation aus."""
    from app import costing, settings_store
    from app.models import InquiryAnalysis

    analysis = InquiryAnalysis.model_validate({
        "customer_name": "X", "customer_contact": None,
        "parts": [{"name": "T", "description": "d", "quantity": 1, "material": "Aluminum 6061",
                   "material_is_assumption": False, "estimated_mass_kg_per_part": 1.0,
                   "estimated_machining_hours_per_part": 10.0, "complexity": "low",
                   "technical_requirements": [], "confidence": 90}],
        "deadline": None, "general_requirements": [], "missing_information": [],
        "assumptions": [], "overall_confidence": 90,
    })
    settings_store.seed_material_prices_if_empty()
    settings_store.update_settings({"pricing": {"hourly_rate": 100.0, "target_margin_pct": 0.5,
                                                "overhead_pct": 0.0, "setup_cost": 0.0,
                                                "complexity": {"low": 1.0}}})
    cost = costing.estimate_costs(analysis)
    # 10 h * 100 €/h * 1.0 = 1000 € Arbeit; Material 4 €/kg * 1 kg = 4 €
    assert cost.parts[0].labor_cost == 1000.0
    assert cost.total_cost == 1004.0          # overhead 0
    assert cost.recommended_price == 2008.0   # /(1-0.5)


def test_material_price_override():
    from app import database, settings_store
    settings_store.seed_material_prices_if_empty()
    database.insert("material_prices", name="Spezialstahl XZ", eur_per_kg=12.5)
    assert settings_store.material_rate("Spezialstahl XZ") == 12.5

"""Modul 11: Globaler KI-Copilot.

Beantwortet Fragen ausschließlich auf Basis echter Systemdaten. Der Copilot
kann keine freien SQL-Queries absetzen, sondern nur eine feste Menge
read-only Abfrage-Werkzeuge aufrufen; jede Antwort ist damit auf konkrete
Datensätze (mit IDs) zurückführbar. Werden keine Daten gefunden, sagt der
Copilot das ausdrücklich — er erfindet nichts.
"""

import json

from . import ai, database, services, settings_store

COPILOT_SYSTEM = """Du bist der Copilot eines KI-gestützten Betriebssystems für \
Fertigungsunternehmen. Beantworte Fragen ausschließlich anhand der Daten, die dir \
die Werkzeuge liefern.

Strikte Regeln:
- Erfinde NIEMALS Zahlen, Kunden, Projekte, Preise, Materialien oder Spezifikationen. \
Nutze nur Werte aus den Werkzeug-Ergebnissen.
- Rufe die nötigen Werkzeuge auf, bevor du antwortest. Reichen die Daten nicht, sage \
das klar ("Dazu liegen keine Daten vor").
- Belege jede Aussage mit den konkreten Datensätzen, z. B. "Angebot #12" oder \
"Projekt #4". So bleibt jede Antwort nachvollziehbar.
- Antworte knapp und auf Deutsch. Bei Unsicherheit weise darauf hin und empfehle eine \
Prüfung."""

# Werkzeuge: jedes liefert echte Datensätze zurück
TOOLS = [
    {
        "name": "list_offers",
        "description": "Listet Angebote, optional gefiltert nach Pipeline-Status "
        "(draft, internal_review, sent, viewed, negotiation, won, lost).",
        "input_schema": {
            "type": "object",
            "properties": {"pipeline_stage": {"type": "string"}},
        },
    },
    {
        "name": "offers_awaiting_approval",
        "description": "Angebote, die auf interne Freigabe warten (Status draft oder "
        "internal_review, noch kein freigegebenes Dokument).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "highest_risk_offer",
        "description": "Das Angebot mit der höchsten Risikobewertung (Severity).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_projects",
        "description": "Listet Projekte, optional gefiltert nach Status "
        "(planned, in_progress, waiting, completed, delivered).",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
        },
    },
    {
        "name": "delayed_projects",
        "description": "Projekte, deren Frist überschritten und die nicht abgeschlossen sind.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "revenue_by_customer",
        "description": "Umsatz und Marge je Kunde aus gewonnenen Angeboten.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analytics_overview",
        "description": "Kennzahlen-Überblick: Vertrieb, Betrieb, Profitabilität.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "post_calculation",
        "description": "Nachkalkulation eines Projekts (Soll vs. Ist) per project_id.",
        "input_schema": {
            "type": "object",
            "properties": {"project_id": {"type": "integer"}},
            "required": ["project_id"],
        },
    },
]


def _offer_brief(o: dict) -> dict:
    return {
        "id": o["id"],
        "customer": o["analysis"].get("customer_name") or o.get("email_from"),
        "pipeline_stage": o["pipeline_stage"],
        "status": o["status"],
        "value": services._offer_value(o),
        "risk_severity": o["risks"].get("overall_severity"),
        "has_document": bool(o["offer_html"]),
    }


def _run_tool(name: str, params: dict) -> object:
    if name == "list_offers":
        stage = params.get("pipeline_stage")
        offers = database.list_offers(
            "pipeline_stage = ?", (stage,)) if stage else database.list_offers()
        return [_offer_brief(o) for o in offers]
    if name == "offers_awaiting_approval":
        return [
            _offer_brief(o)
            for o in database.list_offers()
            if o["status"] in ("draft", "reviewed") and not o["offer_html"]
            or (o["pipeline_stage"] == "internal_review")
        ]
    if name == "highest_risk_offer":
        offers = database.list_offers()
        if not offers:
            return {"message": "Keine Angebote vorhanden."}
        top = max(offers, key=lambda o: o["risks"].get("overall_severity", 0))
        brief = _offer_brief(top)
        brief["risks"] = top["risks"].get("risks", [])
        return brief
    if name == "list_projects":
        status = params.get("status")
        rows = database.fetch_all(
            "projects", "status = ?", (status,)) if status else database.fetch_all("projects")
        return rows
    if name == "delayed_projects":
        return services.analytics_overview()["operations"]["delayed_list"]
    if name == "revenue_by_customer":
        return services.analytics_overview()["profitability"]["by_customer"]
    if name == "analytics_overview":
        return services.analytics_overview()
    if name == "post_calculation":
        try:
            return services.post_calculation(int(params["project_id"]))
        except ValueError as exc:
            return {"error": str(exc)}
    return {"error": f"Unbekanntes Werkzeug: {name}"}


def ask(question: str) -> dict:
    """Beantwortet eine Frage grounded in echten Daten. Gibt Antwort + die
    tatsächlich aufgerufenen Werkzeuge (für Nachvollziehbarkeit) zurück."""
    client = ai.client()
    messages = [{"role": "user", "content": question}]
    used_tools: list[dict] = []

    for _ in range(6):  # begrenzte Werkzeug-Schleife
        response = client.messages.create(
            model=settings_store.ai_model(),
            max_tokens=3000,
            system=COPILOT_SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            answer = next((b.text for b in response.content if b.type == "text"), "")
            return {"answer": answer, "sources": used_tools}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = _run_tool(block.name, block.input or {})
                used_tools.append({"tool": block.name, "input": block.input, "result": output})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(output, ensure_ascii=False, default=str),
                    }
                )
        messages.append({"role": "user", "content": results})

    return {
        "answer": "Die Anfrage war zu komplex für eine eindeutige Auswertung. "
        "Bitte konkreter nachfragen.",
        "sources": used_tools,
    }

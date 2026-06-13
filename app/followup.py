"""Modul 3: Automatischer Follow-up-Assistent.

Überwacht Angebote in der Pipeline und erkennt Anlässe für ein Nachfassen
(keine Reaktion seit X Tagen, Angebot läuft bald ab, Verhandlungssignal).
Die KI entwirft auf Wunsch eine Nachfass-Mail — versendet wird NIE automatisch,
ein Mensch muss jeden Entwurf freigeben.
"""

from datetime import datetime, timezone
from typing import Optional

from . import ai, database, services, settings_store

NO_REPLY_DAYS = 7
EXPIRY_WARN_DAYS = 5

FOLLOWUP_SYSTEM = """Du bist ein höflicher, professioneller Vertriebsassistent eines \
industriellen Fertigungsunternehmens. Entwirf eine kurze, konkrete Nachfass-E-Mail \
auf Deutsch (Sie-Form) zu einem bestehenden Angebot. Beziehe dich nur auf die \
gelieferten Fakten — erfinde keine Preise, Mengen oder Zusagen. Ton: zuvorkommend, \
nicht aufdringlich. Gib nur den E-Mail-Text zurück (Betreff in der ersten Zeile als \
'Betreff: …'), ohne weitere Erklärungen."""


def _parse(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def detect_suggestions() -> list[dict]:
    """Liefert Nachfass-Anlässe für offene Angebote — rein datenbasiert."""
    now = datetime.now(timezone.utc)
    suggestions: list[dict] = []

    for offer in database.list_offers():
        stage = offer["pipeline_stage"]
        if stage not in ("sent", "viewed", "negotiation"):
            continue

        reference = _parse(offer["last_customer_reply_at"]) or _parse(offer["updated_at"])
        days_idle = (now - reference).days if reference else None
        reasons = []

        if days_idle is not None and days_idle >= NO_REPLY_DAYS:
            reasons.append(f"Seit {days_idle} Tagen keine Reaktion des Kunden.")

        valid_until = _parse(offer["valid_until"])
        if valid_until:
            days_left = (valid_until - now).days
            if 0 <= days_left <= EXPIRY_WARN_DAYS:
                reasons.append(f"Angebot läuft in {days_left} Tagen ab.")
            elif days_left < 0:
                reasons.append("Angebot ist bereits abgelaufen.")

        if stage == "negotiation":
            reasons.append("Angebot ist in Verhandlung — aktives Nachfassen sinnvoll.")

        if reasons:
            suggestions.append(
                {
                    "offer_id": offer["id"],
                    "customer": offer["analysis"].get("customer_name")
                    or offer.get("email_from"),
                    "stage": stage,
                    "value": services._offer_value(offer),
                    "days_idle": days_idle,
                    "reasons": reasons,
                }
            )
    return suggestions


def draft_followup(offer_id: int) -> dict:
    """Erzeugt einen KI-Entwurf für eine Nachfass-Mail (nur Entwurf, kein Versand)."""
    offer = database.get_offer(offer_id)
    if offer is None:
        raise ValueError("Angebot nicht gefunden")

    analysis = offer["analysis"]
    facts = (
        f"Kunde: {analysis.get('customer_name') or offer.get('email_from') or 'Kunde'}\n"
        f"Angebotsnummer: {offer_id}\n"
        f"Angebotswert: EUR {services._offer_value(offer):,.2f}\n"
        f"Pipeline-Status: {offer['pipeline_stage']}\n"
        f"Positionen: "
        + ", ".join(p["name"] for p in analysis.get("parts", []))
        + (f"\nGültig bis: {offer['valid_until']}" if offer["valid_until"] else "")
    )
    response = ai.client().messages.create(
        model=settings_store.ai_model(),
        max_tokens=1200,
        system=FOLLOWUP_SYSTEM,
        messages=[{"role": "user", "content": f"Fakten zum Angebot:\n{facts}"}],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")

    activity_id = database.add_activity(
        "offer",
        offer_id,
        text,
        kind="email_draft",
        author="ai",
        meta={"approved": False, "channel": "email"},
    )
    return {"offer_id": offer_id, "activity_id": activity_id, "draft": text}


def approve_followup(activity_id: int) -> dict:
    """Menschliche Freigabe eines Entwurfs. Markiert ihn als freigegeben.
    (Echter Mailversand ist bewusst nicht Teil des MVP.)"""
    activity = database.fetch_one("activities", activity_id)
    if activity is None or activity["kind"] != "email_draft":
        raise ValueError("Entwurf nicht gefunden")
    import json

    meta = json.loads(activity["meta_json"])
    meta["approved"] = True
    meta["approved_at"] = database._now()
    database.update("activities", activity_id, meta=meta)
    database.add_activity(
        "offer", activity["entity_id"],
        "Nachfass-Entwurf freigegeben (bereit zum Versand).",
        kind="status", author="user",
    )
    return {"activity_id": activity_id, "approved": True}

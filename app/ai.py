"""AI core: inquiry structuring (Steps A+B), email classification, risk analysis
(Step D), and offer narrative generation (Step E) using the Claude API.

Cost estimation (Step C) is deterministic and lives in costing.py — the model
only supplies the inputs (quantities, materials, time estimates, complexity).

All model output is German (the system's working language).
"""

import base64
import os

import anthropic

from . import config, settings_store
from .models import (
    CostEstimate,
    EmailClassification,
    InquiryAnalysis,
    OfferNarrative,
    RiskAnalysis,
)

_client: anthropic.Anthropic | None = None


class MissingApiKeyError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY ist nicht gesetzt. Kopiere .env.example nach .env, "
                "trage deinen API-Key von https://console.anthropic.com ein und starte "
                "den Server neu."
            )
        _client = anthropic.Anthropic()
    return _client


EXTRACTION_SYSTEM = """Du bist die Eingangsverarbeitung eines Angebotssystems für \
industrielle Fertigungsunternehmen (CNC-Zerspanung, Sondermaschinenbau, Automatisierung).

Du erhältst unstrukturierte Kundenanfragen: E-Mails, RFQ-Texte, Freitext — teils mit \
angehängten Zeichnungen, PDFs oder Stücklisten. Extrahiere und normalisiere sie in das \
strukturierte Schema.

Regeln:
- Erfasse jedes angefragte Teil bzw. System separat. Werte auch Anhänge (Zeichnungen, \
PDFs, Tabellen) aus.
- Fehlt die Stückzahl, nimm 1 an und dokumentiere das als Annahme.
- Fehlt das Material, leite eine sinnvolle industrielle Wahl ab, setze \
material_is_assumption auf true und dokumentiere es in den Annahmen.
- Schätze Rohmaterialmasse pro Teil (kg) und Fertigungszeit pro Teil (Stunden) mit \
fundiertem Fertigungsverstand; die Werte speisen ein Kostenmodell — realistisch, \
nicht optimistisch.
- Bewerte die Komplexität nach Toleranzen, Featureanzahl und Geometrie: low (einfache \
Dreh-/Frästeile), medium (Mehrseitenbearbeitung, Standardtoleranzen), high (enge \
Toleranzen, 5-Achs, Sonderoberflächen), very_high (Präzisionsbaugruppen, Sonderverfahren).
- Jeder abgeleitete Wert muss in der Annahmenliste mit Konfidenz (0-100) erscheinen.
- Liste alles, was wirklich beim Kunden geklärt werden muss, unter missing_information.
- Schreibe alle Ausgaben auf Deutsch; Kundennamen und Teilebezeichnungen wörtlich übernehmen."""

CLASSIFIER_SYSTEM = """Du bist der E-Mail-Filter eines Angebotssystems für ein \
industrielles Fertigungsunternehmen. Entscheide, ob eine eingehende E-Mail eine \
Kundenanfrage, ein RFQ oder eine Auftragsanfrage ist, für die ein Angebot erstellt \
werden sollte.

Anfragen sind z. B.: Bitte um Angebot, Preisanfrage für Teile/Baugruppen/Maschinen, \
RFQ mit Zeichnungen, Auftragsanbahnung mit technischen Anforderungen.
Keine Anfragen sind z. B.: Newsletter, Werbung, Rechnungen, Lieferstatusfragen, \
Bewerbungen, interne Mails, Spam, reine Terminabsprachen."""

RISK_SYSTEM = """Du bist der Risiko-Prüfer eines industriellen Angebotssystems. \
Identifiziere anhand der strukturierten Interpretation einer Kundenanfrage die Risiken, \
die ein Fertigungsunternehmen vor Angebotsabgabe abwägen sollte: fehlende technische \
Spezifikationen, unklare Toleranzen, Materialunsicherheit, Fertigungsrisiken, \
Terminrisiken, kaufmännische Risiken. Sei konkret und praxisnah — jedes Risiko braucht \
eine Schwere (1 gering bis 5 kritisch) und eine umsetzbare Maßnahme. Erfinde keine \
Risiken, die die Daten nicht hergeben. Schreibe auf Deutsch."""

OFFER_SYSTEM = """Du schreibst professionelle kommerzielle Angebote für ein \
industrielles Fertigungsunternehmen, auf Deutsch. Ton: klar, souverän, industriell — \
kein Marketing-Geschwafel. Sprich den Kunden direkt an (Sie-Form). Preistabelle, \
Annahmen und AGB werden vom System separat gerendert; du schreibst nur die Texte: \
Titel, Einleitung, strukturierten Leistungsumfang, Liefertermin-Aussage und Schluss. \
Leite den Liefertermin aus den geschätzten Fertigungsstunden und einer ggf. genannten \
Frist ab, inklusive realistischem Puffer für Materialbeschaffung."""


def _attachment_blocks(attachments: list[dict]) -> list[dict]:
    """Convert stored attachments into Claude content blocks (PDF, image, text)."""
    blocks: list[dict] = []
    for att in attachments:
        if not att.get("passed_to_ai"):
            continue
        media_type = att["media_type"]
        with open(att["path"], "rb") as f:
            data = f.read()
        if media_type == "application/pdf":
            blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(data).decode(),
                    },
                    "title": att["filename"],
                }
            )
        elif media_type.startswith("image/"):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.standard_b64encode(data).decode(),
                    },
                }
            )
        else:  # text/plain & Co.
            blocks.append(
                {
                    "type": "text",
                    "text": f"<anhang name=\"{att['filename']}\">\n"
                    + data.decode("utf-8", errors="replace")
                    + "\n</anhang>",
                }
            )
    return blocks


def analyze_inquiry(raw_text: str, attachments: list[dict] | None = None) -> InquiryAnalysis:
    """Step A + B: convert raw inquiry (text + attachments) into a structured model."""
    content: list[dict] = [{"type": "text", "text": f"<anfrage>\n{raw_text}\n</anfrage>"}]
    content += _attachment_blocks(attachments or [])
    response = client().messages.parse(
        model=settings_store.ai_model(),
        max_tokens=8000,
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": content}],
        output_format=InquiryAnalysis,
    )
    return response.parsed_output


def classify_email(subject: str, sender: str, body: str) -> EmailClassification:
    """Decide whether an incoming email is a quotable inquiry/order."""
    response = client().messages.parse(
        model=config.ANTHROPIC_FAST_MODEL,
        max_tokens=1000,
        system=CLASSIFIER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Von: {sender}\nBetreff: {subject}\n\n{body[:6000]}",
            }
        ],
        output_format=EmailClassification,
    )
    return response.parsed_output


def analyze_risks(analysis: InquiryAnalysis) -> RiskAnalysis:
    """Step D: risk list with severity scores."""
    response = client().messages.parse(
        model=settings_store.ai_model(),
        max_tokens=6000,
        system=RISK_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": "Strukturierte Interpretation der Anfrage:\n"
                + analysis.model_dump_json(indent=2),
            }
        ],
        output_format=RiskAnalysis,
    )
    return response.parsed_output


def generate_offer_narrative(
    analysis: InquiryAnalysis, costing: CostEstimate, final_price: float
) -> OfferNarrative:
    """Step E: narrative sections of the commercial offer."""
    context = (
        "Strukturierte Interpretation der Anfrage:\n"
        + analysis.model_dump_json(indent=2)
        + "\n\nKostenkalkulation:\n"
        + costing.model_dump_json(indent=2)
        + f"\n\nFinaler Angebotspreis (diese Zahl verwenden): EUR {final_price:,.2f}"
    )
    response = client().messages.parse(
        model=settings_store.ai_model(),
        max_tokens=6000,
        system=OFFER_SYSTEM,
        messages=[{"role": "user", "content": context}],
        output_format=OfferNarrative,
    )
    return response.parsed_output

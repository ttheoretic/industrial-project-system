"""FastAPI-Anwendung: Anfrage → strukturiertes Verständnis → Kalkulation →
Review → Angebot. Start mit:  uvicorn app.main:app --reload
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, costing, database, email_intake, pipeline, renderer
from .models import (
    CostEstimate,
    InquiryAnalysis,
    PriceOverride,
    StatusUpdate,
)

app = FastAPI(title="Industrielles Angebotssystem", version="0.2.0")


@app.exception_handler(ai.MissingApiKeyError)
def missing_api_key_handler(request, exc: ai.MissingApiKeyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Erlaubte Statusübergänge
ALLOWED_TRANSITIONS = {
    "draft": {"reviewed", "rejected"},
    "reviewed": {"sent", "rejected", "draft"},
    "sent": {"accepted", "rejected"},
    "accepted": set(),
    "rejected": {"draft"},
}


@app.on_event("startup")
def startup() -> None:
    database.init_db()
    email_intake.start_background_polling()


def _get_or_404(offer_id: int) -> dict:
    offer = database.get_offer(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden")
    return offer


# ---------------------------------------------------------------------------
# Pipeline: manuelle Erfassung (Text + Dateien) → KI-Analyse → Entwurf
# ---------------------------------------------------------------------------


@app.post("/api/inquiries")
async def create_inquiry(
    text: str = Form(""),
    customer_email: Optional[str] = Form(None),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """Neue Anfrage verarbeiten: extrahieren, Annahmen, Kalkulation, Risiken; als Entwurf speichern."""
    file_data = [(f.filename or "datei", await f.read()) for f in files]
    if not text.strip() and not any(data for _, data in file_data):
        raise HTTPException(status_code=400, detail="Anfragetext oder Dateien erforderlich")
    try:
        return pipeline.process_inquiry(
            text=text.strip() or "(Kein Anschreiben — siehe angehängte Dateien.)",
            customer_email=customer_email,
            files=file_data,
        )
    except pipeline.NoQuotablePartsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# E-Mail-Eingang
# ---------------------------------------------------------------------------


@app.get("/api/email/status")
def email_status() -> dict:
    return {"configured": email_intake.is_configured(), **email_intake.state}


@app.post("/api/email/check")
def email_check_now() -> dict:
    """Postfach sofort abrufen (zusätzlich zum automatischen Polling)."""
    if not email_intake.is_configured():
        raise HTTPException(
            status_code=409,
            detail="IMAP ist nicht konfiguriert. IMAP_HOST, IMAP_USER und "
            "IMAP_PASSWORD in der .env setzen.",
        )
    try:
        return email_intake.check_mailbox()
    except ai.MissingApiKeyError:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"E-Mail-Abruf fehlgeschlagen: {exc}")


# ---------------------------------------------------------------------------
# Review: lesen, Interpretation bearbeiten, Preis übersteuern
# ---------------------------------------------------------------------------


@app.get("/api/offers")
def list_offers() -> list[dict]:
    return database.list_offers()


@app.get("/api/offers/{offer_id}")
def get_offer(offer_id: int) -> dict:
    return _get_or_404(offer_id)


@app.get("/api/offers/{offer_id}/attachments/{index}")
def download_attachment(offer_id: int, index: int) -> FileResponse:
    offer = _get_or_404(offer_id)
    try:
        att = offer["attachments"][index]
    except IndexError:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    if not Path(att["path"]).is_file():
        raise HTTPException(status_code=410, detail="Datei nicht mehr vorhanden")
    return FileResponse(att["path"], filename=att["filename"], media_type=att["media_type"])


@app.put("/api/offers/{offer_id}/analysis")
def update_analysis(offer_id: int, analysis: InquiryAnalysis) -> dict:
    """Reviewer bearbeitet Mengen, Materialien, Zeitschätzungen, Annahmen.
    Die Kalkulation wird neu berechnet; ein Preis-Override wird zurückgesetzt."""
    offer = _get_or_404(offer_id)
    if offer["status"] in ("sent", "accepted"):
        raise HTTPException(status_code=409, detail="Angebot bereits versendet; nicht editierbar")
    cost = costing.estimate_costs(analysis)
    database.update_offer(
        offer_id,
        analysis=analysis.model_dump(),
        costing=cost.model_dump(),
        final_price=None,
        offer_html=None,
        status="draft",
    )
    return database.get_offer(offer_id)


@app.post("/api/offers/{offer_id}/price")
def override_price(offer_id: int, payload: PriceOverride) -> dict:
    offer = _get_or_404(offer_id)
    if offer["status"] in ("sent", "accepted"):
        raise HTTPException(status_code=409, detail="Angebot bereits versendet; nicht editierbar")
    if payload.final_price <= 0:
        raise HTTPException(status_code=400, detail="Preis muss positiv sein")
    database.update_offer(offer_id, final_price=payload.final_price, offer_html=None)
    return database.get_offer(offer_id)


# ---------------------------------------------------------------------------
# Ausgabe: Freigabe (Dokument erzeugen), Statusverfolgung
# ---------------------------------------------------------------------------


@app.post("/api/offers/{offer_id}/approve")
def approve_offer(offer_id: int) -> dict:
    """Geprüftes Angebot freigeben: finales Dokument erzeugen, Status → reviewed."""
    offer = _get_or_404(offer_id)
    if offer["status"] not in ("draft", "reviewed"):
        raise HTTPException(
            status_code=409, detail=f"Freigabe aus Status '{offer['status']}' nicht möglich"
        )

    analysis = InquiryAnalysis.model_validate(offer["analysis"])
    cost = CostEstimate.model_validate(offer["costing"])
    final_price = offer["final_price"] or cost.recommended_price

    narrative = ai.generate_offer_narrative(analysis, cost, final_price)
    html_doc = renderer.render_offer_html(offer_id, narrative, analysis, cost, final_price)

    database.update_offer(
        offer_id, status="reviewed", final_price=final_price, offer_html=html_doc
    )
    return database.get_offer(offer_id)


@app.post("/api/offers/{offer_id}/status")
def set_status(offer_id: int, payload: StatusUpdate) -> dict:
    offer = _get_or_404(offer_id)
    current = offer["status"]
    if payload.status not in ALLOWED_TRANSITIONS[current]:
        raise HTTPException(
            status_code=409,
            detail=f"Ungültiger Statuswechsel: {current} → {payload.status}",
        )
    if payload.status == "sent" and not offer["offer_html"]:
        raise HTTPException(status_code=409, detail="Angebot vor dem Versand erst freigeben")
    database.update_offer(offer_id, status=payload.status)
    return database.get_offer(offer_id)


@app.get("/api/offers/{offer_id}/document", response_class=HTMLResponse)
def get_document(offer_id: int) -> str:
    offer = _get_or_404(offer_id)
    if not offer["offer_html"]:
        raise HTTPException(status_code=404, detail="Angebotsdokument noch nicht erzeugt")
    return offer["offer_html"]


# ---------------------------------------------------------------------------
# Review-Oberfläche
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

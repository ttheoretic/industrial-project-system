"""FastAPI application: inquiry → structured understanding → pricing → review → offer.

Run with:  uvicorn app.main:app --reload
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import ai, costing, database, renderer
from .models import (
    CostEstimate,
    InquiryAnalysis,
    InquiryCreate,
    PriceOverride,
    StatusUpdate,
)

app = FastAPI(title="Industrial Quotation System", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Status transitions allowed from each state
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


def _get_or_404(offer_id: int) -> dict:
    offer = database.get_offer(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


# ---------------------------------------------------------------------------
# Pipeline: inquiry intake → AI analysis → costing → draft offer
# ---------------------------------------------------------------------------


@app.post("/api/inquiries")
def create_inquiry(payload: InquiryCreate) -> dict:
    """Process a raw customer inquiry: extract, assume, cost, assess risk; store as draft."""
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Inquiry text is empty")

    analysis = ai.analyze_inquiry(payload.text)
    if not analysis.parts:
        raise HTTPException(
            status_code=422,
            detail="No quotable parts or systems could be identified in the inquiry",
        )
    cost = costing.estimate_costs(analysis)
    risks = ai.analyze_risks(analysis)

    offer_id = database.create_offer(
        raw_inquiry=payload.text,
        customer_email=payload.customer_email,
        analysis=analysis.model_dump(),
        costing=cost.model_dump(),
        risks=risks.model_dump(),
    )
    return database.get_offer(offer_id)


# ---------------------------------------------------------------------------
# Review layer: read, edit interpretation, override price
# ---------------------------------------------------------------------------


@app.get("/api/offers")
def list_offers() -> list[dict]:
    return database.list_offers()


@app.get("/api/offers/{offer_id}")
def get_offer(offer_id: int) -> dict:
    return _get_or_404(offer_id)


@app.put("/api/offers/{offer_id}/analysis")
def update_analysis(offer_id: int, analysis: InquiryAnalysis) -> dict:
    """Reviewer edits quantities, materials, time estimates, assumptions.
    Costing is recomputed from the edited analysis; a price override is cleared."""
    offer = _get_or_404(offer_id)
    if offer["status"] in ("sent", "accepted"):
        raise HTTPException(status_code=409, detail="Offer already sent; cannot edit")
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
        raise HTTPException(status_code=409, detail="Offer already sent; cannot edit")
    if payload.final_price <= 0:
        raise HTTPException(status_code=400, detail="Price must be positive")
    database.update_offer(offer_id, final_price=payload.final_price, offer_html=None)
    return database.get_offer(offer_id)


# ---------------------------------------------------------------------------
# Output actions: approve (generate final document), status tracking
# ---------------------------------------------------------------------------


@app.post("/api/offers/{offer_id}/approve")
def approve_offer(offer_id: int) -> dict:
    """Approve the reviewed offer: generate the final document, status → reviewed."""
    offer = _get_or_404(offer_id)
    if offer["status"] not in ("draft", "reviewed"):
        raise HTTPException(status_code=409, detail=f"Cannot approve from '{offer['status']}'")

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
            detail=f"Invalid transition: {current} → {payload.status}",
        )
    if payload.status == "sent" and not offer["offer_html"]:
        raise HTTPException(status_code=409, detail="Approve the offer before sending")
    database.update_offer(offer_id, status=payload.status)
    return database.get_offer(offer_id)


@app.get("/api/offers/{offer_id}/document", response_class=HTMLResponse)
def get_document(offer_id: int) -> str:
    offer = _get_or_404(offer_id)
    if not offer["offer_html"]:
        raise HTTPException(status_code=404, detail="Offer document not generated yet")
    return offer["offer_html"]


# ---------------------------------------------------------------------------
# Review UI
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

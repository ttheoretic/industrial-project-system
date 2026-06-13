"""FastAPI-Anwendung — KI-Betriebssystem für Fertigungsunternehmen.

Grundlage bleibt der Angebots-Workflow (Anfrage → Analyse → Kalkulation →
Angebot). Darauf bauen CRM, Sales-Pipeline, Follow-up, Auftragswandlung,
Projekt-/Material-/Produktionsplanung, Zeiterfassung, Nachkalkulation,
Dokumente, Copilot und Analytics auf.
"""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (
    ai,
    config,
    copilot,
    costing,
    database,
    email_intake,
    followup,
    pipeline,
    renderer,
    services,
)
from .models import (
    ActivityCreate,
    CompanyCreate,
    ContactCreate,
    CopilotQuery,
    CostEstimate,
    InquiryAnalysis,
    MachineCreate,
    MaterialCreate,
    MaterialUpdate,
    PipelineUpdate,
    PriceOverride,
    ProjectUpdate,
    SlotCreate,
    StatusUpdate,
    TaskCreate,
    TaskUpdate,
    TimeEntryCreate,
)

app = FastAPI(title="Fertigungs-Betriebssystem", version="0.3.0")


@app.exception_handler(ai.MissingApiKeyError)
def missing_api_key_handler(request, exc: ai.MissingApiKeyError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
def validation_handler(request: Request, exc: RequestValidationError):
    """Verständliche statt kryptischer 422-Meldung (häufig bei veraltetem
    Frontend-Cache, das einen ungültigen Wert sendet)."""
    problems = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={"detail": f"Ungültige Anfrage ({problems}). Tipp: Seite mit "
                 "Strg+Shift+R neu laden, falls eine alte Version im Cache steckt."},
    )


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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


def _get_offer_or_404(offer_id: int) -> dict:
    offer = database.get_offer(offer_id)
    if offer is None:
        raise HTTPException(status_code=404, detail="Angebot nicht gefunden")
    return offer


def _get_or_404(table: str, row_id: int, label: str) -> dict:
    row = database.fetch_one(table, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} nicht gefunden")
    return row


# ===========================================================================
# Angebots-Pipeline: manuelle Erfassung (Text + Dateien) → Entwurf
# ===========================================================================


@app.post("/api/inquiries")
async def create_inquiry(
    text: str = Form(""),
    customer_email: Optional[str] = Form(None),
    company_id: Optional[int] = Form(None),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    file_data = [(f.filename or "datei", await f.read()) for f in files]
    if not text.strip() and not any(data for _, data in file_data):
        raise HTTPException(status_code=400, detail="Anfragetext oder Dateien erforderlich")
    try:
        return pipeline.process_inquiry(
            text=text.strip() or "(Kein Anschreiben — siehe angehängte Dateien.)",
            customer_email=customer_email,
            files=file_data,
            company_id=company_id,
        )
    except pipeline.NoQuotablePartsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ===========================================================================
# E-Mail-Eingang
# ===========================================================================


@app.get("/api/email/status")
def email_status() -> dict:
    return {"configured": email_intake.is_configured(), **email_intake.state}


@app.post("/api/email/check")
def email_check_now() -> dict:
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


# ===========================================================================
# Angebote: Review, Bearbeitung, Freigabe, Pipeline
# ===========================================================================


@app.get("/api/offers")
def list_offers() -> list[dict]:
    return database.list_offers()


@app.get("/api/offers/{offer_id}")
def get_offer(offer_id: int) -> dict:
    offer = _get_offer_or_404(offer_id)
    offer["activities"] = database.list_activities("offer", offer_id)
    return offer


@app.get("/api/offers/{offer_id}/attachments/{index}")
def download_attachment(offer_id: int, index: int) -> FileResponse:
    offer = _get_offer_or_404(offer_id)
    try:
        att = offer["attachments"][index]
    except IndexError:
        raise HTTPException(status_code=404, detail="Anhang nicht gefunden")
    if not Path(att["path"]).is_file():
        raise HTTPException(status_code=410, detail="Datei nicht mehr vorhanden")
    return FileResponse(att["path"], filename=att["filename"], media_type=att["media_type"])


@app.put("/api/offers/{offer_id}/analysis")
def update_analysis(offer_id: int, analysis: InquiryAnalysis) -> dict:
    offer = _get_offer_or_404(offer_id)
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
    offer = _get_offer_or_404(offer_id)
    if offer["status"] in ("sent", "accepted"):
        raise HTTPException(status_code=409, detail="Angebot bereits versendet; nicht editierbar")
    if payload.final_price <= 0:
        raise HTTPException(status_code=400, detail="Preis muss positiv sein")
    database.update_offer(offer_id, final_price=payload.final_price, offer_html=None)
    return database.get_offer(offer_id)


@app.post("/api/offers/{offer_id}/approve")
def approve_offer(offer_id: int) -> dict:
    offer = _get_offer_or_404(offer_id)
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
        offer_id, status="reviewed", pipeline_stage="internal_review",
        final_price=final_price, offer_html=html_doc,
    )
    database.add_activity("offer", offer_id, "Angebot freigegeben & Dokument erzeugt.",
                          kind="status")
    return database.get_offer(offer_id)


@app.post("/api/offers/{offer_id}/status")
def set_status(offer_id: int, payload: StatusUpdate) -> dict:
    offer = _get_offer_or_404(offer_id)
    current = offer["status"]
    if payload.status not in ALLOWED_TRANSITIONS[current]:
        raise HTTPException(
            status_code=409, detail=f"Ungültiger Statuswechsel: {current} → {payload.status}"
        )
    if payload.status == "sent" and not offer["offer_html"]:
        raise HTTPException(status_code=409, detail="Angebot vor dem Versand erst freigeben")
    stage_map = {"sent": "sent", "accepted": "won", "rejected": "lost"}
    fields = {"status": payload.status}
    if payload.status in stage_map:
        fields["pipeline_stage"] = stage_map[payload.status]
    database.update_offer(offer_id, **fields)
    if payload.status == "accepted":
        services.convert_offer_to_project(offer_id)
    return database.get_offer(offer_id)


@app.get("/api/offers/{offer_id}/document", response_class=HTMLResponse)
def get_document(offer_id: int) -> str:
    offer = _get_offer_or_404(offer_id)
    if not offer["offer_html"]:
        raise HTTPException(status_code=404, detail="Angebotsdokument noch nicht erzeugt")
    return offer["offer_html"]


# ===========================================================================
# Modul 2: Sales-Pipeline
# ===========================================================================


@app.get("/api/pipeline")
def get_pipeline() -> dict:
    board: dict[str, list] = {s: [] for s in services.PIPELINE_STAGES}
    for o in database.list_offers():
        board.setdefault(o["pipeline_stage"], []).append(
            {
                "id": o["id"],
                "customer": o["analysis"].get("customer_name") or o.get("email_from"),
                "value": services._offer_value(o),
                "risk": o["risks"].get("overall_severity"),
                "updated_at": o["updated_at"],
            }
        )
    return board


@app.post("/api/offers/{offer_id}/pipeline")
def set_pipeline_stage(offer_id: int, payload: PipelineUpdate) -> dict:
    offer = _get_offer_or_404(offer_id)
    database.update_offer(offer_id, pipeline_stage=payload.stage)
    database.add_activity("offer", offer_id, f"Pipeline-Status → {payload.stage}", kind="status")
    if payload.stage == "won":
        project = services.convert_offer_to_project(offer_id)
        return {"offer": database.get_offer(offer_id), "project": project}
    if payload.stage == "lost":
        database.update_offer(offer_id, status="rejected")
    return {"offer": database.get_offer(offer_id)}


@app.post("/api/offers/{offer_id}/activity")
def add_offer_activity(offer_id: int, payload: ActivityCreate) -> dict:
    _get_offer_or_404(offer_id)
    if payload.kind == "customer_reply":
        database.update_offer(offer_id, last_customer_reply_at=database._now())
    aid = database.add_activity("offer", offer_id, payload.body, kind=payload.kind, author="user")
    return {"activity_id": aid, "activities": database.list_activities("offer", offer_id)}


# ===========================================================================
# Modul 3: Follow-up-Assistent
# ===========================================================================


@app.get("/api/followups")
def followup_suggestions() -> list[dict]:
    return followup.detect_suggestions()


@app.post("/api/offers/{offer_id}/followup/draft")
def followup_draft(offer_id: int) -> dict:
    _get_offer_or_404(offer_id)
    return followup.draft_followup(offer_id)


@app.post("/api/followups/{activity_id}/approve")
def followup_approve(activity_id: int) -> dict:
    try:
        return followup.approve_followup(activity_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ===========================================================================
# Modul 1: CRM
# ===========================================================================


@app.get("/api/companies")
def list_companies(q: str = "") -> list[dict]:
    if q:
        like = f"%{q}%"
        return database.fetch_all(
            "companies", "name LIKE ? OR email LIKE ? OR industry LIKE ?",
            (like, like, like), order="name",
        )
    return database.fetch_all("companies", order="name")


@app.post("/api/companies")
def create_company(payload: CompanyCreate) -> dict:
    cid = database.insert("companies", updated_at=database._now(), **payload.model_dump())
    return database.fetch_one("companies", cid)


@app.get("/api/companies/{company_id}")
def get_company(company_id: int) -> dict:
    company = _get_or_404("companies", company_id, "Firma")
    company["contacts"] = database.fetch_all("contacts", "company_id = ?", (company_id,))
    company["offers"] = [
        {
            "id": o["id"], "stage": o["pipeline_stage"], "value": services._offer_value(o),
            "created_at": o["created_at"],
        }
        for o in database.list_offers("company_id = ?", (company_id,))
    ]
    company["projects"] = database.fetch_all("projects", "company_id = ?", (company_id,))
    company["activities"] = database.list_activities("company", company_id)
    return company


@app.put("/api/companies/{company_id}")
def update_company(company_id: int, payload: CompanyCreate) -> dict:
    _get_or_404("companies", company_id, "Firma")
    database.update("companies", company_id, **payload.model_dump())
    return database.fetch_one("companies", company_id)


@app.post("/api/companies/{company_id}/contacts")
def add_contact(company_id: int, payload: ContactCreate) -> dict:
    _get_or_404("companies", company_id, "Firma")
    cid = database.insert("contacts", company_id=company_id, **payload.model_dump())
    return database.fetch_one("contacts", cid)


@app.post("/api/companies/{company_id}/activity")
def add_company_activity(company_id: int, payload: ActivityCreate) -> dict:
    _get_or_404("companies", company_id, "Firma")
    database.add_activity("company", company_id, payload.body, kind=payload.kind, author="user")
    return {"activities": database.list_activities("company", company_id)}


# ===========================================================================
# Modul 5: Projektmanagement
# ===========================================================================


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return database.fetch_all("projects")


@app.get("/api/projects/{project_id}")
def get_project(project_id: int) -> dict:
    project = _get_or_404("projects", project_id, "Projekt")
    project["tasks"] = database.fetch_all("tasks", "project_id = ?", (project_id,), order="id")
    project["materials"] = database.fetch_all("materials", "project_id = ?", (project_id,), order="id")
    project["time_entries"] = database.fetch_all(
        "time_entries", "project_id = ?", (project_id,), order="entry_date DESC")
    project["activities"] = database.list_activities("project", project_id)
    project["post_calculation"] = services.post_calculation(project_id)
    return project


@app.put("/api/projects/{project_id}")
def update_project(project_id: int, payload: ProjectUpdate) -> dict:
    _get_or_404("projects", project_id, "Projekt")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if fields:
        database.update("projects", project_id, **fields)
    if "status" in fields:
        database.add_activity("project", project_id, f"Status → {fields['status']}", kind="status")
    return database.fetch_one("projects", project_id)


@app.post("/api/projects/{project_id}/tasks")
def add_task(project_id: int, payload: TaskCreate) -> dict:
    _get_or_404("projects", project_id, "Projekt")
    data = payload.model_dump()
    data["is_milestone"] = 1 if data["is_milestone"] else 0
    tid = database.insert("tasks", project_id=project_id, **data)
    return database.fetch_one("tasks", tid)


@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate) -> dict:
    _get_or_404("tasks", task_id, "Aufgabe")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    database.update("tasks", task_id, **fields)
    return database.fetch_one("tasks", task_id)


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int) -> dict:
    database.delete("tasks", task_id)
    return {"deleted": task_id}


# ===========================================================================
# Modul 6: Materialplanung
# ===========================================================================


@app.post("/api/projects/{project_id}/materials")
def add_material(project_id: int, payload: MaterialCreate) -> dict:
    _get_or_404("projects", project_id, "Projekt")
    mid = database.insert("materials", project_id=project_id, **payload.model_dump())
    return database.fetch_one("materials", mid)


@app.put("/api/materials/{material_id}")
def update_material(material_id: int, payload: MaterialUpdate) -> dict:
    _get_or_404("materials", material_id, "Material")
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    database.update("materials", material_id, **fields)
    return database.fetch_one("materials", material_id)


@app.delete("/api/materials/{material_id}")
def delete_material(material_id: int) -> dict:
    database.delete("materials", material_id)
    return {"deleted": material_id}


@app.get("/api/procurement")
def procurement_suggestions() -> list[dict]:
    """Beschaffungsvorschläge: alle benötigten, noch nicht bestellten Materialien."""
    rows = database.query(
        "SELECT m.*, p.name AS project_name FROM materials m "
        "JOIN projects p ON p.id = m.project_id WHERE m.status = 'needed' ORDER BY m.supplier"
    )
    return rows


# ===========================================================================
# Modul 7: Produktionsplanung
# ===========================================================================


@app.get("/api/production")
def production_board() -> dict:
    machines = database.fetch_all("machines", order="name")
    slots = database.fetch_all("production_slots", order="start_date")
    for m in machines:
        booked = sum(s["hours"] or 0 for s in slots if s["machine_id"] == m["id"])
        m["booked_hours"] = booked
        m["utilization_pct"] = (
            round(booked / m["capacity_hours_per_week"] * 100, 1)
            if m["capacity_hours_per_week"] else None
        )
    return {"machines": machines, "slots": slots}


@app.post("/api/machines")
def add_machine(payload: MachineCreate) -> dict:
    mid = database.insert("machines", **payload.model_dump())
    return database.fetch_one("machines", mid)


@app.delete("/api/machines/{machine_id}")
def delete_machine(machine_id: int) -> dict:
    database.delete("machines", machine_id)
    return {"deleted": machine_id}


@app.post("/api/production/slots")
def add_slot(payload: SlotCreate) -> dict:
    _get_or_404("machines", payload.machine_id, "Maschine")
    sid = database.insert("production_slots", **payload.model_dump())
    return database.fetch_one("production_slots", sid)


@app.delete("/api/production/slots/{slot_id}")
def delete_slot(slot_id: int) -> dict:
    database.delete("production_slots", slot_id)
    return {"deleted": slot_id}


# ===========================================================================
# Modul 8: Zeiterfassung
# ===========================================================================


@app.post("/api/projects/{project_id}/time")
def log_time(project_id: int, payload: TimeEntryCreate) -> dict:
    _get_or_404("projects", project_id, "Projekt")
    tid = database.insert("time_entries", project_id=project_id, **payload.model_dump())
    return database.fetch_one("time_entries", tid)


@app.delete("/api/time/{entry_id}")
def delete_time(entry_id: int) -> dict:
    database.delete("time_entries", entry_id)
    return {"deleted": entry_id}


# ===========================================================================
# Modul 9: Nachkalkulation
# ===========================================================================


@app.get("/api/projects/{project_id}/post-calculation")
def project_post_calculation(project_id: int) -> dict:
    try:
        return services.post_calculation(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ===========================================================================
# Modul 10: Dokumentenverwaltung
# ===========================================================================


@app.get("/api/documents")
def list_documents(
    q: str = "", company_id: Optional[int] = None, project_id: Optional[int] = None
) -> list[dict]:
    clauses, params = [], []
    if q:
        clauses.append("name LIKE ?")
        params.append(f"%{q}%")
    if company_id:
        clauses.append("company_id = ?")
        params.append(company_id)
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    where = " AND ".join(clauses)
    return database.fetch_all("documents", where, tuple(params), order="name, version DESC")


@app.post("/api/documents")
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form("Dokument"),
    company_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    offer_id: Optional[int] = Form(None),
) -> dict:
    data = await file.read()
    upload_dir = Path(config.UPLOAD_DIR) / "documents"
    upload_dir.mkdir(parents=True, exist_ok=True)
    name = file.filename or "dokument"
    # Versionierung: gleiche Name+Bezug → nächste Version
    prior = database.fetch_all(
        "documents", "name = ? AND IFNULL(company_id,0)=? AND IFNULL(project_id,0)=?",
        (name, company_id or 0, project_id or 0),
    )
    version = max((d["version"] for d in prior), default=0) + 1
    path = upload_dir / f"{uuid.uuid4().hex}_{name}"
    path.write_bytes(data)
    did = database.insert(
        "documents", name=name, kind=kind, path=str(path),
        media_type=file.content_type, size_bytes=len(data), version=version,
        company_id=company_id, project_id=project_id, offer_id=offer_id,
    )
    return database.fetch_one("documents", did)


@app.get("/api/documents/{doc_id}/download")
def download_document(doc_id: int) -> FileResponse:
    doc = _get_or_404("documents", doc_id, "Dokument")
    if not Path(doc["path"]).is_file():
        raise HTTPException(status_code=410, detail="Datei nicht mehr vorhanden")
    return FileResponse(doc["path"], filename=doc["name"], media_type=doc["media_type"])


# ===========================================================================
# Modul 11: KI-Copilot (grounded)
# ===========================================================================


@app.post("/api/copilot")
def copilot_ask(payload: CopilotQuery) -> dict:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Frage ist leer")
    return copilot.ask(payload.question)


# ===========================================================================
# Modul 12: Analytics
# ===========================================================================


@app.get("/api/analytics")
def analytics() -> dict:
    return services.analytics_overview()


# ===========================================================================
# Oberfläche
# ===========================================================================


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

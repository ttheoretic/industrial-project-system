"""Shared intake pipeline: save attachments, run AI analysis + costing + risks,
store the draft offer. Used by both the manual API endpoint and the email intake.
"""

import re
import uuid
from pathlib import Path
from typing import Optional

from . import ai, config, costing, database


class NoQuotablePartsError(ValueError):
    pass


def _safe_filename(name: str) -> str:
    name = Path(name or "datei").name
    return re.sub(r"[^\w.\-äöüÄÖÜß ]", "_", name)[:120] or "datei"


def save_attachments(files: list[tuple[str, bytes]]) -> list[dict]:
    """Persist uploaded/attached files to disk; mark which ones the AI can read."""
    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    for filename, data in files:
        if not data or len(data) > config.MAX_ATTACHMENT_BYTES:
            continue
        safe = _safe_filename(filename)
        suffix = Path(safe).suffix.lower()
        media_type = config.SUPPORTED_ATTACHMENT_TYPES.get(suffix)
        path = upload_dir / f"{uuid.uuid4().hex}_{safe}"
        path.write_bytes(data)
        saved.append(
            {
                "filename": safe,
                "path": str(path),
                "media_type": media_type or "application/octet-stream",
                "size_bytes": len(data),
                "passed_to_ai": media_type is not None,
            }
        )
    return saved


def _match_or_create_company(analysis_name: Optional[str], email: Optional[str]) -> Optional[int]:
    """Verknüpft die Anfrage mit einer Firma (CRM): vorhandene per Name/E-Mail
    finden oder neu anlegen — keine Doppelerfassung."""
    name = (analysis_name or "").strip()
    if not name and not email:
        return None
    for company in database.fetch_all("companies"):
        if name and company["name"].strip().lower() == name.lower():
            return company["id"]
        if email and company.get("email") and company["email"].lower() == email.lower():
            return company["id"]
    if not name:
        return None
    return database.insert("companies", name=name, email=email, updated_at=database._now())


def process_inquiry(
    text: str,
    customer_email: Optional[str] = None,
    files: Optional[list[tuple[str, bytes]]] = None,
    source: str = "manual",
    email_from: Optional[str] = None,
    email_subject: Optional[str] = None,
    company_id: Optional[int] = None,
) -> dict:
    """Full pipeline: inquiry → analysis → costing → risks → stored draft offer.
    Verknüpft das Angebot automatisch mit einem CRM-Firmendatensatz."""
    attachments = save_attachments(files or [])

    analysis = ai.analyze_inquiry(text, attachments)
    if not analysis.parts:
        raise NoQuotablePartsError(
            "In der Anfrage konnten keine anbietbaren Teile oder Systeme erkannt werden."
        )
    cost = costing.estimate_costs(analysis)
    risks = ai.analyze_risks(analysis)

    if company_id is None:
        company_id = _match_or_create_company(analysis.customer_name, customer_email)

    offer_id = database.create_offer(
        raw_inquiry=text,
        customer_email=customer_email,
        analysis=analysis.model_dump(),
        costing=cost.model_dump(),
        risks=risks.model_dump(),
        source=source,
        email_from=email_from,
        email_subject=email_subject,
        attachments=attachments,
        company_id=company_id,
    )
    return database.get_offer(offer_id)

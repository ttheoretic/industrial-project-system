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


def process_inquiry(
    text: str,
    customer_email: Optional[str] = None,
    files: Optional[list[tuple[str, bytes]]] = None,
    source: str = "manual",
    email_from: Optional[str] = None,
    email_subject: Optional[str] = None,
) -> dict:
    """Full pipeline: inquiry → analysis → costing → risks → stored draft offer."""
    attachments = save_attachments(files or [])

    analysis = ai.analyze_inquiry(text, attachments)
    if not analysis.parts:
        raise NoQuotablePartsError(
            "In der Anfrage konnten keine anbietbaren Teile oder Systeme erkannt werden."
        )
    cost = costing.estimate_costs(analysis)
    risks = ai.analyze_risks(analysis)

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
    )
    return database.get_offer(offer_id)

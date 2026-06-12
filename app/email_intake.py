"""Automatischer E-Mail-Eingang: pollt ein IMAP-Postfach, erkennt per KI, ob eine
Mail eine Auftrags-/Angebotsanfrage ist, und lädt sie inkl. Anhängen ins System.

Aktiv, sobald IMAP_HOST/IMAP_USER/IMAP_PASSWORD gesetzt sind. Verarbeitete Mails
werden über das IMAP-Flag \\Seen markiert; es werden nur ungelesene Mails geholt.
"""

import email
import email.header
import email.utils
import imaplib
import logging
import re
import threading
import time
from datetime import datetime, timezone

from . import ai, config, pipeline

logger = logging.getLogger("email_intake")

# Status für die UI / das Monitoring
state = {
    "enabled": False,
    "last_check": None,
    "last_error": None,
    "processed": 0,   # als Anfrage erkannt und importiert
    "skipped": 0,     # geprüft, aber keine Anfrage
}

_stop = threading.Event()


def is_configured() -> bool:
    return bool(config.IMAP_HOST and config.IMAP_USER and config.IMAP_PASSWORD)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = email.header.decode_header(value)
    return "".join(
        p.decode(enc or "utf-8", errors="replace") if isinstance(p, bytes) else p
        for p, enc in parts
    )


def _strip_html(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _extract(msg: email.message.Message) -> tuple[str, list[tuple[str, bytes]]]:
    """Mail-Body (Text bevorzugt, sonst HTML) und Anhänge extrahieren."""
    body_text, body_html = "", ""
    attachments: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = part.get_filename()
        if "attachment" in disposition or filename:
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append((_decode(filename), payload))
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, errors="replace")
        if part.get_content_type() == "text/plain" and not body_text:
            body_text = text
        elif part.get_content_type() == "text/html" and not body_html:
            body_html = text
    return body_text or _strip_html(body_html), attachments


def check_mailbox() -> dict:
    """Einmaliger Abruf: ungelesene Mails prüfen und Anfragen importieren."""
    result = {"checked": 0, "imported": [], "skipped": []}
    with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select(config.IMAP_FOLDER)
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            # BODY[] setzt \Seen — jede Mail wird genau einmal geprüft
            _, msg_data = imap.fetch(num, "(BODY[])")
            msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode(msg.get("Subject"))
            sender_name, sender_addr = email.utils.parseaddr(msg.get("From", ""))
            sender = f"{_decode(sender_name)} <{sender_addr}>".strip()
            body, attachments = _extract(msg)
            result["checked"] += 1

            classification = ai.classify_email(subject, sender, body)
            if not classification.is_inquiry:
                state["skipped"] += 1
                result["skipped"].append({"subject": subject, "reason": classification.reasoning})
                logger.info("Übersprungen: %s (%s)", subject, classification.reasoning)
                continue

            text = f"Betreff: {subject}\nVon: {sender}\n\n{body}"
            try:
                offer = pipeline.process_inquiry(
                    text=text,
                    customer_email=sender_addr or None,
                    files=attachments,
                    source="email",
                    email_from=sender,
                    email_subject=subject,
                )
                state["processed"] += 1
                result["imported"].append({"offer_id": offer["id"], "subject": subject})
                logger.info("Importiert als Angebot #%s: %s", offer["id"], subject)
            except pipeline.NoQuotablePartsError as exc:
                state["skipped"] += 1
                result["skipped"].append({"subject": subject, "reason": str(exc)})
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    state["last_error"] = None
    return result


def _loop() -> None:
    while not _stop.wait(config.EMAIL_POLL_INTERVAL_SECONDS):
        try:
            check_mailbox()
        except Exception as exc:  # Verbindung/Login/API — weiterlaufen, Fehler merken
            state["last_error"] = str(exc)
            logger.exception("E-Mail-Abruf fehlgeschlagen")


def start_background_polling() -> None:
    if not is_configured():
        logger.info("E-Mail-Eingang inaktiv (IMAP nicht konfiguriert)")
        return
    state["enabled"] = True
    threading.Thread(target=_loop, daemon=True, name="email-intake").start()
    logger.info(
        "E-Mail-Eingang aktiv: %s alle %ss", config.IMAP_HOST, config.EMAIL_POLL_INTERVAL_SECONDS
    )

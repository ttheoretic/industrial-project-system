"""Tests für Datei-Verarbeitung und E-Mail-Parsing (ohne API-Key lauffähig)."""

from email.message import EmailMessage

from app.email_intake import _extract
from app.pipeline import save_attachments


def test_save_attachments_classifies_ai_readable(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    saved = save_attachments(
        [
            ("zeichnung.pdf", b"%PDF-1.4 fake"),
            ("foto.PNG", b"\x89PNG fake"),
            ("notiz.txt", b"50 Stk Halterungen"),
            ("modell.step", b"ISO-10303-21"),
            ("leer.pdf", b""),
        ]
    )
    by_name = {a["filename"]: a for a in saved}
    assert by_name["zeichnung.pdf"]["passed_to_ai"] is True
    assert by_name["zeichnung.pdf"]["media_type"] == "application/pdf"
    assert by_name["foto.PNG"]["passed_to_ai"] is True
    assert by_name["notiz.txt"]["passed_to_ai"] is True
    # STEP-Dateien werden gespeichert, aber nicht an die KI gegeben
    assert by_name["modell.step"]["passed_to_ai"] is False
    # leere Dateien werden verworfen
    assert "leer.pdf" not in by_name


def test_save_attachments_sanitizes_filenames(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    saved = save_attachments([("../../etc/passwd", b"x")])
    assert saved[0]["filename"] == "passwd"
    assert str(tmp_path) in saved[0]["path"]


def test_email_extract_body_and_attachments():
    msg = EmailMessage()
    msg["Subject"] = "Anfrage Frästeile"
    msg["From"] = "Max Mustermann <max@kunde.de>"
    msg.set_content("Bitte um Angebot für 20 Frästeile aus Edelstahl.")
    msg.add_attachment(
        b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="zeichnung.pdf"
    )
    body, attachments = _extract(msg)
    assert "20 Frästeile" in body
    assert attachments == [("zeichnung.pdf", b"%PDF-1.4 fake")]


def test_email_extract_html_fallback():
    msg = EmailMessage()
    msg.set_content("<p>Bitte um <b>Angebot</b></p><script>x()</script>", subtype="html")
    body, attachments = _extract(msg)
    assert "Angebot" in body
    assert "script" not in body.lower() or "x()" not in body
    assert attachments == []

# KI-Betriebssystem für Fertigungsunternehmen

Ein KI-gestütztes Betriebssystem für industrielle Fertigung (CNC-Zerspanung,
Sondermaschinenbau, Automatisierung). Es deckt den kompletten Lebenszyklus in
**einem** System ab — von der Kundenanfrage bis zur Nachkalkulation:

```
Anfrage → KI-Analyse → Kalkulation → Angebot → Follow-up → Auftrag gewonnen
→ Projekt → Produktionsplanung → Materialplanung → Ausführung → Zeiterfassung
→ Lieferung → Nachkalkulation → Analytics
```

Der Angebots-Workflow (siehe unten) ist die Grundlage; darauf bauen zwölf Module auf.

## Module

| # | Modul | Funktion |
|---|---|---|
| – | **Angebote** (Kern) | Anfrage (E-Mail/manuell, inkl. Dateien) → KI-Analyse → Kalkulation → Risiko → Prüfung → Angebotsdokument |
| 1 | **CRM** | Firmen, Kontakte, Kundenhistorie, Timeline, Notizen; Angebote/Projekte je Kunde verknüpft |
| 2 | **Sales-Pipeline** | Kanban über Angebotsstatus (Entwurf → Prüfung → Versendet → Angesehen → Verhandlung → Gewonnen/Verloren), Deal-Werte, Aktivitäten |
| 3 | **Follow-up-Assistent** | KI erkennt Nachfass-Anlässe (>7 Tage keine Reaktion, baldiger Ablauf, Verhandlung) und entwirft Mails — **Versand nur nach menschlicher Freigabe** |
| 4 | **Auftragswandlung** | „Gewonnen" erzeugt automatisch Projekt + Aufgaben + Materialbedarf aus der Angebotsanalyse — keine Doppelerfassung |
| 5 | **Projektmanagement** | Status, Aufgaben, Meilensteine, Notizen, Verantwortliche |
| 6 | **Materialplanung** | Materiallisten, Lieferanten, Status, Beschaffungsvorschläge |
| 7 | **Produktionsplanung** | Maschinen, Arbeitszentren, Kapazität, Einplanung, Auslastung (Sichtbarkeit, kein ERP-Ersatz) |
| 8 | **Zeiterfassung** | Stunden je Projekt/Aufgabe, Soll vs. Ist |
| 9 | **Nachkalkulation** | Soll (Angebot) vs. Ist (Zeit + Material): Material-, Arbeits-, Margenabweichung |
| 10 | **Dokumente** | Zentrale Ablage (Zeichnungen, PDFs, Angebote), Suche, Versionierung, kunden-/projektbezogen |
| 11 | **KI-Copilot** | Globaler Assistent — beantwortet Fragen **nur aus echten Datensätzen** (Tool-Use), jede Antwort belegbar, keine Halluzination |
| 12 | **Analytics-Dashboard** | Vertrieb (Umsatz, Abschlussquote), Betrieb (aktive/verspätete Projekte, Maschinenauslastung), Profitabilität je Kunde |

### KI-Sicherheit
Die KI erfindet keine Kosten, Materialien oder Spezifikationen: Die Preisberechnung
ist deterministischer Code, Annahmen werden ausdrücklich mit Konfidenz markiert, und
der Copilot ist über read-only Abfrage-Werkzeuge strikt an reale Datensätze gebunden
(jede Antwort verweist auf die genutzten Datenquellen). Bei geringer Konfidenz wird
zur Prüfung aufgefordert.

---

## Angebots-Kern (Grundlage)

**Pipeline:** Anfrage (E-Mail oder manuell, inkl. Dateien) → strukturiertes Verständnis →
Kalkulation → Risikoanalyse → menschliche Prüfung → Angebot → Versand

## Funktionsweise

| Schritt | Was passiert | Wo |
|---|---|---|
| Eingang per E-Mail | IMAP-Postfach wird automatisch gepollt; die KI erkennt, ob eine Mail eine Auftrags-/Angebotsanfrage ist, und importiert sie inkl. Anhängen | `app/email_intake.py` |
| Eingang manuell | Text einfügen und/oder Dateien hochladen (PDF, Bilder, TXT/CSV) | UI „+ Neue Anfrage" |
| A. Verstehen | Claude extrahiert Kunde, Positionen, Mengen, Materialien, Anforderungen, Termine — auch aus PDF-Zeichnungen und Bildern | `app/ai.py` (`analyze_inquiry`) |
| B. Annahmen | Fehlende Werte werden abgeleitet und explizit als Annahmen mit Konfidenz (0–100 %) gekennzeichnet | gleicher Aufruf, Feld `assumptions` |
| C. Kalkulation | **Deterministisches** Kostenmodell: Materialpreistabelle × geschätzte Masse + Fertigungsstunden × Stundensatz × Komplexitätsfaktor + Rüstkosten, dann Gemeinkosten-% und Zielmarge | `app/costing.py`, Parameter in `app/config.py` |
| D. Risikoanalyse | Claude markiert fehlende Spezifikationen, unklare Toleranzen, Material-, Fertigungs- und Terminrisiken mit Schwere 1–5 | `app/ai.py` (`analyze_risks`) |
| E. Angebotserstellung | Claude schreibt die Texte (Leistungsumfang, Liefertermin); das System rendert ein druckfertiges HTML-Angebot mit Preistabelle, Annahmen und AGB-Platzhalter | `app/ai.py` + `app/renderer.py` |
| Prüfung | Drei-Panel-UI: Original-Anfrage / editierbare KI-Interpretation / Kalkulation & Preis. Mengen, Material, Zeiten anpassen; Preis übersteuern; freigeben oder ablehnen | `static/` |
| Verfolgung | Status-Workflow: `Entwurf → Geprüft → Versendet → Angenommen/Abgelehnt` (CRM light, SQLite) | `app/database.py`, `app/main.py` |

Die KI *interpretiert* nur (Mengen, Materialien, Zeitschätzungen, Komplexität);
die Preisberechnung selbst läuft im Code — nachvollziehbar und reproduzierbar.

## Startseite & Stammdaten

Beim Öffnen landest du auf der **Startseite**: Überblick über alle Module plus ein
**Einrichtungs-Check** (Firmendaten, KI-Schlüssel, E-Mail, Materialpreise).

Unter **Einstellungen** pflegst du alles, was je Unternehmen unterschiedlich ist —
diese Werte fließen direkt in Kalkulation und Angebotsdokument ein:
- **Firmendaten/Briefkopf:** Name, Adresse, USt-IdNr., Logo (erscheint im Angebot)
- **Pauschalen:** Stundensatz, Rüstkosten, Gemeinkosten-%, Zielmarge, Komplexitätsfaktoren
- **Kaufmännisches:** Währung, USt-Satz, Zahlungsbedingungen, Angebotsgültigkeit, AGB-Text
- **Materialpreisliste:** pflegbare €/kg-Tabelle (ersetzt die fest verdrahteten Defaults)

## Desktop-App (.exe / .app)

Die App läuft als Web-App im Browser **und** als eigenständiges Desktop-Fenster
(gleiche Funktionalität, wie bei Notion). Desktop lokal starten:

```bash
pip install pywebview
python desktop.py
```

Zum Erzeugen einer ausführbaren Datei siehe Kopf von `desktop.py` (PyInstaller).
Hinweis: Eine Windows-`.exe` muss unter Windows gebaut werden, eine macOS-`.app`
unter macOS — ein Cross-Build ist nicht möglich.

## Einrichtung

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY eintragen
uvicorn app.main:app --reload
```

http://localhost:8000 öffnen — Anfrage über **+ Neue Anfrage** einfügen oder hochladen.

API-Dokumentation: http://localhost:8000/docs

## Automatischer E-Mail-Eingang

In der `.env` das Postfach konfigurieren — danach werden ungelesene Mails alle
2 Minuten geprüft (Intervall einstellbar):

```
IMAP_HOST=imap.dein-anbieter.de
IMAP_USER=anfragen@deine-firma.de
IMAP_PASSWORD=...
```

- Die KI klassifiziert jede neue Mail: Anfrage/RFQ/Auftrag → wird automatisch
  inkl. Anhängen importiert; Newsletter, Rechnungen, Spam → übersprungen.
- Über den Button **„E-Mails abrufen"** in der UI lässt sich der Abruf sofort auslösen.
- Bei Gmail/Outlook ist ein App-Passwort nötig (IMAP aktivieren).

## Dateianhänge

PDF, PNG/JPG/GIF/WebP und TXT/CSV/MD werden direkt von der KI mitgelesen
(z. B. Zeichnungen, Stücklisten). Andere Formate (z. B. STEP) werden gespeichert
und im Review verlinkt, aber nicht analysiert. Max. 20 MB pro Datei.

## API-Übersicht

| Methode & Pfad | Zweck |
|---|---|
| `POST /api/inquiries` (multipart) | Anfrage verarbeiten: `text`, `customer_email`, `files[]` → Entwurf |
| `POST /api/email/check` | Postfach sofort abrufen |
| `GET /api/email/status` | Status des E-Mail-Eingangs |
| `GET /api/offers` / `GET /api/offers/{id}` | Angebote auflisten / lesen |
| `GET /api/offers/{id}/attachments/{n}` | Anhang herunterladen |
| `PUT /api/offers/{id}/analysis` | Prüfer-Änderungen speichern; Kalkulation wird neu berechnet |
| `POST /api/offers/{id}/price` | Finalen Preis übersteuern |
| `POST /api/offers/{id}/approve` | Angebotsdokument erzeugen, Status → `Geprüft` |
| `POST /api/offers/{id}/status` | Status setzen: `sent`, `accepted`, `rejected` |
| `GET /api/offers/{id}/document` | Druckfertiges HTML-Angebot (im Browser „Als PDF drucken") |

## Kostenmodell anpassen

`app/config.py` (oder Umgebungsvariablen): Stundensatz, Gemeinkosten-%, Zielmarge,
Materialpreistabelle (€/kg), Komplexitätsfaktoren, Rüstkosten.

## Tests

Der deterministische Kern (Kostenmodell, Material-Lookup, Dokument-Renderer,
Datei-/E-Mail-Parsing) ist ohne API-Key testbar:

```bash
pip install pytest
pytest
```

## MVP-Grenzen (bewusst)

Kein ERP, keine CAD-Verarbeitung (STEP-Dateien werden gespeichert, nicht analysiert),
keine Produktionsplanung, kein automatischer Mailversand. Spätere Ausbaustufen
(CRM, Projektmanagement, Lieferantenanbindung, Zeichnungsanalyse, automatische
Nachfassmails, KPI-Auswertung) bauen auf den gespeicherten Angebotsdaten auf.

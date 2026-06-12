# Industrial Quotation System (MVP)

AI-powered quotation system for industrial manufacturing companies (CNC machining,
special machine building, automation). Converts unstructured customer inquiries into
structured, reviewable, sendable commercial offers.

**Pipeline:** inquiry → structured understanding → pricing → risk analysis → human review → offer → send

## How it works

| Step | What happens | Where |
|---|---|---|
| A. Understanding | Claude extracts customer, parts, quantities, materials, requirements, deadlines into a structured model | `app/ai.py` (`analyze_inquiry`) |
| B. Assumptions | Missing values are inferred, explicitly labeled as assumptions with per-field confidence scores (0–100%) | same call, `assumptions` field |
| C. Cost estimation | **Deterministic** cost engine: material lookup table × estimated mass + machining hours × hourly rate × complexity factor + setup cost, then overhead % and target margin | `app/costing.py`, parameters in `app/config.py` |
| D. Risk analysis | Claude flags missing specs, unclear tolerances, material uncertainty, production/deadline risks with severity 1–5 | `app/ai.py` (`analyze_risks`) |
| E. Offer generation | Claude writes the narrative (scope of work, timeline); the system renders a PDF-ready HTML offer with pricing table, assumptions section, and terms placeholder | `app/ai.py` + `app/renderer.py` |
| Review | Three-panel UI: original inquiry / AI interpretation (editable) / cost & pricing. Edit quantities, materials, time estimates; override price; approve or reject | `static/` |
| Tracking | Offer status workflow: `draft → reviewed → sent → accepted/rejected` (CRM-light, SQLite) | `app/database.py`, `app/main.py` |

The AI only *interprets* (quantities, materials, time estimates, complexity);
pricing itself is computed in code so it is auditable and reproducible.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Open http://localhost:8000 — paste a customer inquiry via **+ New Inquiry**.

API docs: http://localhost:8000/docs

## API overview

| Method & path | Purpose |
|---|---|
| `POST /api/inquiries` | Process raw inquiry → AI analysis + costing + risks → draft offer |
| `GET /api/offers` / `GET /api/offers/{id}` | List / read offers |
| `PUT /api/offers/{id}/analysis` | Save reviewer edits; costing is recomputed |
| `POST /api/offers/{id}/price` | Override the final price |
| `POST /api/offers/{id}/approve` | Generate final offer document, status → `reviewed` |
| `POST /api/offers/{id}/status` | Track status: `sent`, `accepted`, `rejected` |
| `GET /api/offers/{id}/document` | The PDF-ready HTML offer (print to PDF from the browser) |

## Tuning the cost model

Edit `app/config.py` (or set env vars): hourly rate, overhead %, target margin,
material €/kg table, complexity factors, setup cost.

## Tests

The deterministic core (cost engine, material lookup, document renderer) is tested
without any API key:

```bash
pip install pytest
pytest
```

## MVP constraints (by design)

No ERP, no CAD processing, no scheduling, no integrations. Attachments are ignored
unless pasted as text. Future extensions (CRM, project management, supplier
integration, drawing analysis, follow-up automation, KPI analytics) build on the
stored offer records.

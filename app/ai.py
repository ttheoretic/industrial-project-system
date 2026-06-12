"""AI core: inquiry structuring (Steps A+B), risk analysis (Step D),
and offer narrative generation (Step E) using the Claude API.

Cost estimation (Step C) is deterministic and lives in costing.py — the model
only supplies the inputs (quantities, materials, time estimates, complexity).
"""

import os

import anthropic

from . import config
from .models import CostEstimate, InquiryAnalysis, OfferNarrative, RiskAnalysis

_client: anthropic.Anthropic | None = None


class MissingApiKeyError(RuntimeError):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env, add your "
                "API key from https://console.anthropic.com, and restart the server."
            )
        _client = anthropic.Anthropic()
    return _client


EXTRACTION_SYSTEM = """You are the intake engine of a quotation system for industrial \
manufacturing companies (CNC machining, special machine building, automation systems).

You receive unstructured customer inquiries: emails, RFQ text, free-text descriptions. \
Extract and normalize them into the structured schema.

Rules:
- Extract every requested part or system separately.
- If quantity is missing, assume 1 and record it as an assumption.
- If material is missing, infer a reasonable industrial choice, set \
material_is_assumption to true, and record it in assumptions.
- Estimate raw material mass per part (kg) and production time per part (hours) \
using sound manufacturing judgment; these feed a cost model, so be realistic, not optimistic.
- Rate complexity by tolerances, feature count, and geometry: low (simple turned/milled \
parts), medium (multi-setup milling, standard tolerances), high (tight tolerances, \
5-axis, special finishes), very_high (precision assemblies, exotic processes).
- Every inferred value must appear in the assumptions list with a confidence score (0-100).
- List anything that genuinely needs customer clarification under missing_information.
- Write all output in English regardless of the inquiry language, but keep customer \
names and part designations verbatim."""

RISK_SYSTEM = """You are the risk reviewer of an industrial quotation system. Given a \
structured interpretation of a customer inquiry, identify risks a manufacturing company \
should weigh before quoting: missing technical specs, unclear tolerances, material \
uncertainty, production risks, deadline risks, and commercial risks. Be concrete and \
practical — each risk needs a severity (1 minor to 5 critical) and an actionable \
mitigation. Do not invent risks that the data does not support."""

OFFER_SYSTEM = """You write professional commercial offers for an industrial \
manufacturing company. Tone: clear, confident, industrial — no marketing fluff. \
Address the customer directly. The pricing table, assumptions section, and terms are \
rendered separately by the system; you write only the narrative parts: title, \
introduction, structured scope of work, delivery timeline, and closing. Base the \
timeline on the estimated production hours and any stated deadline, including a \
realistic buffer for material procurement."""


def analyze_inquiry(raw_text: str) -> InquiryAnalysis:
    """Step A + B: convert raw inquiry text into a structured, assumption-labeled model."""
    response = client().messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=EXTRACTION_SYSTEM,
        messages=[{"role": "user", "content": f"<inquiry>\n{raw_text}\n</inquiry>"}],
        output_format=InquiryAnalysis,
    )
    return response.parsed_output


def analyze_risks(analysis: InquiryAnalysis) -> RiskAnalysis:
    """Step D: risk list with severity scores."""
    response = client().messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=RISK_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": "Structured inquiry interpretation:\n"
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
        "Structured inquiry interpretation:\n"
        + analysis.model_dump_json(indent=2)
        + "\n\nCost estimate:\n"
        + costing.model_dump_json(indent=2)
        + f"\n\nFinal offer price (use this figure): EUR {final_price:,.2f}"
    )
    response = client().messages.parse(
        model=config.ANTHROPIC_MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=OFFER_SYSTEM,
        messages=[{"role": "user", "content": context}],
        output_format=OfferNarrative,
    )
    return response.parsed_output

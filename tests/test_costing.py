"""Tests for the deterministic parts of the system (no API key required)."""

from app import config
from app.costing import estimate_costs
from app.models import (
    Assumption,
    CostEstimate,
    ExtractedPart,
    InquiryAnalysis,
    OfferNarrative,
)
from app.renderer import render_offer_html


def make_analysis(**overrides) -> InquiryAnalysis:
    part = ExtractedPart(
        name="Mounting bracket",
        description="Milled aluminum bracket",
        quantity=10,
        material="Aluminum 6061",
        material_is_assumption=False,
        estimated_mass_kg_per_part=0.5,
        estimated_machining_hours_per_part=1.5,
        complexity="medium",
        technical_requirements=["±0.05 mm on bore"],
        confidence=85,
    )
    base = dict(
        customer_name="ACME GmbH",
        customer_contact="buyer@acme.example",
        parts=[part],
        deadline="6 weeks",
        general_requirements=[],
        missing_information=["Surface finish not specified"],
        assumptions=[
            Assumption(
                field="surface finish",
                assumption="Standard anodized finish",
                rationale="Common for aluminum brackets",
                confidence=70,
            )
        ],
        overall_confidence=80,
    )
    base.update(overrides)
    return InquiryAnalysis(**base)


def test_cost_breakdown_per_part():
    cost = estimate_costs(make_analysis())
    assert len(cost.parts) == 1
    p = cost.parts[0]
    # material: 4.00 €/kg * 0.5 kg * 10 pcs
    assert p.material_cost == 20.00
    # labor: 1.5 h * 10 pcs * 95 €/h * 1.3 (medium)
    assert p.labor_cost == round(15 * 95 * 1.3, 2)
    assert p.setup_cost == config.SETUP_COST_EUR_PER_PART_TYPE
    assert p.subtotal == round(p.material_cost + p.labor_cost + p.setup_cost, 2)


def test_totals_overhead_and_margin():
    cost = estimate_costs(make_analysis())
    assert cost.direct_cost == cost.parts[0].subtotal
    assert cost.overhead_cost == round(cost.direct_cost * config.OVERHEAD_PERCENT, 2)
    assert cost.total_cost == round(cost.direct_cost + cost.overhead_cost, 2)
    expected_price = cost.total_cost / (1 - config.TARGET_MARGIN_PERCENT)
    assert abs(cost.recommended_price - expected_price) < 0.01
    assert cost.margin_eur == round(cost.recommended_price - cost.total_cost, 2)


def test_unknown_material_uses_default_rate():
    analysis = make_analysis()
    analysis.parts[0].material = "Unobtainium XQ-9"
    cost = estimate_costs(analysis)
    assert cost.parts[0].material_rate_eur_per_kg == config.DEFAULT_MATERIAL_COST_EUR_PER_KG


def test_material_lookup_tolerates_variations():
    assert config.material_rate("Stainless Steel 304") == 4.50
    assert config.material_rate("aluminum 6061-T6") == 4.00


def test_renderer_produces_complete_document():
    analysis = make_analysis()
    cost = estimate_costs(analysis)
    narrative = OfferNarrative(
        title="Offer for Mounting Brackets",
        introduction="Thank you for your inquiry.",
        scope_of_work=["Machining of 10 brackets", "Anodizing"],
        delivery_timeline="Delivery within 5 weeks of order.",
        closing="We look forward to your order.",
    )
    html = render_offer_html(7, narrative, analysis, cost, cost.recommended_price)
    assert "Offer for Mounting Brackets" in html
    assert "Mounting bracket" in html
    assert "Annahmen" in html
    assert "Standard anodized finish" in html
    # German number formatting: 12,345.67 -> 12.345,67
    german_price = f"{cost.recommended_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    assert german_price in html
    # HTML-escapes untrusted content
    analysis.parts[0].name = "<script>alert(1)</script>"
    cost2 = estimate_costs(analysis)
    html2 = render_offer_html(8, narrative, analysis, cost2, 1000.0)
    assert "<script>alert(1)</script>" not in html2

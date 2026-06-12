"""Step C: deterministic cost estimation from the structured inquiry analysis.

material cost (lookup table) + machining time x hourly rate x complexity factor
+ per-part setup cost, then overhead percentage and target margin.
"""

from . import config
from .models import CostEstimate, InquiryAnalysis, PartCost


def estimate_costs(analysis: InquiryAnalysis) -> CostEstimate:
    parts: list[PartCost] = []
    for part in analysis.parts:
        rate = config.material_rate(part.material)
        material_cost = rate * part.estimated_mass_kg_per_part * part.quantity
        complexity_factor = config.COMPLEXITY_FACTORS[part.complexity]
        machining_hours_total = part.estimated_machining_hours_per_part * part.quantity
        labor_cost = (
            machining_hours_total * config.HOURLY_PRODUCTION_RATE_EUR * complexity_factor
        )
        setup_cost = config.SETUP_COST_EUR_PER_PART_TYPE
        parts.append(
            PartCost(
                part_name=part.name,
                quantity=part.quantity,
                material=part.material,
                material_rate_eur_per_kg=rate,
                material_cost=round(material_cost, 2),
                machining_hours_total=round(machining_hours_total, 2),
                complexity_factor=complexity_factor,
                labor_cost=round(labor_cost, 2),
                setup_cost=setup_cost,
                subtotal=round(material_cost + labor_cost + setup_cost, 2),
            )
        )

    direct_cost = sum(p.subtotal for p in parts)
    overhead_cost = direct_cost * config.OVERHEAD_PERCENT
    total_cost = direct_cost + overhead_cost
    margin = config.TARGET_MARGIN_PERCENT
    recommended_price = total_cost / (1 - margin) if margin < 1 else total_cost

    return CostEstimate(
        parts=parts,
        direct_cost=round(direct_cost, 2),
        overhead_percent=config.OVERHEAD_PERCENT,
        overhead_cost=round(overhead_cost, 2),
        total_cost=round(total_cost, 2),
        target_margin_percent=margin,
        recommended_price=round(recommended_price, 2),
        margin_eur=round(recommended_price - total_cost, 2),
    )

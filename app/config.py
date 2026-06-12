"""Central configuration for the quotation system."""

import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("QUOTE_DB_PATH", "quotes.db")

ANTHROPIC_MODEL = "claude-opus-4-8"

# Pricing parameters (MVP simplified cost model)
HOURLY_PRODUCTION_RATE_EUR = float(os.getenv("HOURLY_PRODUCTION_RATE_EUR", "95.0"))
OVERHEAD_PERCENT = float(os.getenv("OVERHEAD_PERCENT", "0.15"))
TARGET_MARGIN_PERCENT = float(os.getenv("TARGET_MARGIN_PERCENT", "0.30"))

# Material cost lookup table (EUR per kg, rough industrial averages)
MATERIAL_COSTS_EUR_PER_KG = {
    "steel s235": 1.20,
    "steel s355": 1.40,
    "steel c45": 1.80,
    "tool steel": 8.50,
    "stainless steel 304": 4.50,
    "stainless steel 316": 6.00,
    "aluminum 6061": 4.00,
    "aluminum 7075": 7.50,
    "aluminum 5083": 4.80,
    "brass": 8.00,
    "copper": 10.50,
    "titanium grade 5": 45.00,
    "pom": 4.20,
    "peek": 95.00,
    "abs": 3.00,
    "polycarbonate": 5.00,
}
DEFAULT_MATERIAL_COST_EUR_PER_KG = 5.00

# Complexity factor multipliers applied to machining time cost
COMPLEXITY_FACTORS = {
    "low": 1.0,
    "medium": 1.3,
    "high": 1.7,
    "very_high": 2.2,
}

# Setup cost charged once per distinct part (programming, fixturing)
SETUP_COST_EUR_PER_PART_TYPE = 150.0


def material_rate(material: str) -> float:
    """Look up EUR/kg for a material name, tolerant of naming variations."""
    key = material.strip().lower()
    if key in MATERIAL_COSTS_EUR_PER_KG:
        return MATERIAL_COSTS_EUR_PER_KG[key]
    for name, rate in MATERIAL_COSTS_EUR_PER_KG.items():
        if name in key or key in name:
            return rate
    return DEFAULT_MATERIAL_COST_EUR_PER_KG

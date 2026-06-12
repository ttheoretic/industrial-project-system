"""Pydantic schemas: AI extraction output, costing results, risks, and API payloads."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Step A + B: structured understanding of the inquiry, with labeled assumptions
# ---------------------------------------------------------------------------

Complexity = Literal["low", "medium", "high", "very_high"]


class ExtractedPart(BaseModel):
    name: str = Field(description="Short identifying name of the part or system")
    description: str = Field(description="What the part is, in one or two sentences")
    quantity: int = Field(description="Requested quantity; assume 1 if not stated")
    material: str = Field(
        description="Material, e.g. 'Aluminum 6061', 'Stainless steel 304'. "
        "Infer a reasonable industrial choice if not stated."
    )
    material_is_assumption: bool = Field(
        description="True if the material was inferred rather than stated by the customer"
    )
    estimated_mass_kg_per_part: float = Field(
        description="Rough estimated raw material mass per part in kg"
    )
    estimated_machining_hours_per_part: float = Field(
        description="Rough estimated production/machining time per part in hours"
    )
    complexity: Complexity = Field(
        description="Manufacturing complexity based on tolerances, features, and geometry"
    )
    technical_requirements: list[str] = Field(
        description="Stated technical requirements: tolerances, finishes, certifications"
    )
    confidence: int = Field(description="Confidence 0-100 that this part was interpreted correctly")


class Assumption(BaseModel):
    field: str = Field(description="Which field or topic the assumption covers")
    assumption: str = Field(description="The assumption made")
    rationale: str = Field(description="Why this is a reasonable industrial assumption")
    confidence: int = Field(description="Confidence 0-100 in this assumption")


class InquiryAnalysis(BaseModel):
    customer_name: Optional[str] = Field(description="Customer or company name if identifiable")
    customer_contact: Optional[str] = Field(description="Email or contact details if present")
    parts: list[ExtractedPart]
    deadline: Optional[str] = Field(description="Requested delivery deadline as stated, or null")
    general_requirements: list[str] = Field(
        description="Project-level requirements not tied to a single part"
    )
    missing_information: list[str] = Field(
        description="Information that should be clarified with the customer"
    )
    assumptions: list[Assumption]
    overall_confidence: int = Field(description="Overall interpretation confidence 0-100")


# ---------------------------------------------------------------------------
# Step C: cost estimation (computed deterministically, not by the model)
# ---------------------------------------------------------------------------


class PartCost(BaseModel):
    part_name: str
    quantity: int
    material: str
    material_rate_eur_per_kg: float
    material_cost: float
    machining_hours_total: float
    complexity_factor: float
    labor_cost: float
    setup_cost: float
    subtotal: float


class CostEstimate(BaseModel):
    parts: list[PartCost]
    direct_cost: float
    overhead_percent: float
    overhead_cost: float
    total_cost: float
    target_margin_percent: float
    recommended_price: float
    margin_eur: float


# ---------------------------------------------------------------------------
# Step D: risk analysis
# ---------------------------------------------------------------------------

RiskCategory = Literal[
    "missing_specification",
    "unclear_tolerances",
    "material_uncertainty",
    "production_risk",
    "deadline_risk",
    "commercial_risk",
]


class Risk(BaseModel):
    category: RiskCategory
    description: str
    severity: int = Field(description="Severity 1 (minor) to 5 (critical)")
    mitigation: str = Field(description="Recommended mitigation or clarification to request")


class RiskAnalysis(BaseModel):
    risks: list[Risk]
    overall_severity: int = Field(description="Overall risk score 1-5")
    summary: str = Field(description="One-paragraph risk summary for the reviewer")


# ---------------------------------------------------------------------------
# Step E: offer narrative (pricing table is rendered from CostEstimate)
# ---------------------------------------------------------------------------


class OfferNarrative(BaseModel):
    title: str = Field(description="Short professional title for the offer")
    introduction: str = Field(description="Professional opening paragraph addressed to the customer")
    scope_of_work: list[str] = Field(description="Structured scope-of-work bullet points")
    delivery_timeline: str = Field(
        description="Realistic delivery timeline statement based on the work and any deadline"
    )
    closing: str = Field(description="Professional closing paragraph")


# ---------------------------------------------------------------------------
# API payloads / stored record
# ---------------------------------------------------------------------------

OfferStatus = Literal["draft", "reviewed", "sent", "accepted", "rejected"]


class EmailClassification(BaseModel):
    """Decision whether an incoming email is a quotable customer inquiry/order."""

    is_inquiry: bool = Field(
        description="True if the email is a customer inquiry, RFQ, or order request "
        "that should be quoted; false for newsletters, invoices, spam, internal mail, etc."
    )
    reasoning: str = Field(description="Short justification in German")
    confidence: int = Field(description="Confidence 0-100")


class AttachmentMeta(BaseModel):
    filename: str
    path: str
    media_type: str
    size_bytes: int
    passed_to_ai: bool


class PriceOverride(BaseModel):
    final_price: float


class StatusUpdate(BaseModel):
    status: OfferStatus


class OfferRecord(BaseModel):
    id: int
    status: OfferStatus
    source: Literal["manual", "email"]
    raw_inquiry: str
    customer_email: Optional[str]
    email_from: Optional[str]
    email_subject: Optional[str]
    attachments: list[AttachmentMeta]
    analysis: InquiryAnalysis
    costing: CostEstimate
    risks: RiskAnalysis
    final_price: Optional[float]
    offer_html: Optional[str]
    created_at: str
    updated_at: str

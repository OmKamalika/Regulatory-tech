"""
DPDPA 2023 Penalty Schedule — Section 33

Defines the penalty tiers for violations of the Digital Personal Data
Protection Act, 2023. Penalties are absolute amounts (not % of revenue).
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class PenaltyTier:
    """A single penalty tier from DPDPA Section 33"""
    tier_id: str                          # e.g., "PEN-001"
    section_ref: str                      # e.g., "Section 33(a)"
    description: str                      # what violation this covers
    max_penalty_crore: int                # max penalty in crore INR
    max_penalty_display: str              # human-readable display
    applicable_categories: List[str]      # which rule categories trigger this


PENALTY_TIERS = [
    PenaltyTier(
        tier_id="PEN-001",
        section_ref="Section 33(a)",
        description="Failure to take reasonable security safeguards to prevent personal data breach",
        max_penalty_crore=250,
        max_penalty_display="250 crore INR (~$30M USD)",
        applicable_categories=["data_fiduciary_obligations", "sdf_obligations", "data_retention", "cross_border", "video_pii"],
    ),
    PenaltyTier(
        tier_id="PEN-002",
        section_ref="Section 33(b)",
        description="Failure to notify the Data Protection Board and affected Data Principals of a personal data breach",
        max_penalty_crore=200,
        max_penalty_display="200 crore INR (~$24M USD)",
        applicable_categories=["breach_notification"],
    ),
    PenaltyTier(
        tier_id="PEN-003",
        section_ref="Section 33(c)",
        description="Violations related to processing of children's personal data",
        max_penalty_crore=200,
        max_penalty_display="200 crore INR (~$24M USD)",
        applicable_categories=["children_data"],
    ),
    PenaltyTier(
        tier_id="PEN-004",
        section_ref="Section 33(d)",
        description="Failure to obtain valid consent or provide required notice before processing",
        max_penalty_crore=150,
        max_penalty_display="150 crore INR (~$18M USD)",
        applicable_categories=["consent", "purpose_limitation"],
    ),
    PenaltyTier(
        tier_id="PEN-005",
        section_ref="Section 33(e)",
        description="Failure to fulfill obligations related to Data Principal rights (access, correction, erasure, grievance)",
        max_penalty_crore=100,
        max_penalty_display="100 crore INR (~$12M USD)",
        applicable_categories=["data_principal_rights"],
    ),
]


def get_penalty_for_category(category: str) -> PenaltyTier:
    """Get the applicable penalty tier for a rule category"""
    for tier in PENALTY_TIERS:
        if category in tier.applicable_categories:
            return tier
    return PENALTY_TIERS[0]  # default to highest


def get_max_penalty_display(category: str) -> str:
    """Get the human-readable max penalty for a category"""
    tier = get_penalty_for_category(category)
    return f"{tier.section_ref} - up to {tier.max_penalty_display}"

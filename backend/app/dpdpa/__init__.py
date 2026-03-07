"""
DPDPA 2023 + 2025 Rules — Compliance Rule Definitions Package

Provides structured, machine-readable compliance rules based on
India's Digital Personal Data Protection Act, 2023 and DPDP Rules, 2025.
"""

from app.dpdpa.definitions import (
    DPDPARule,
    DPDPA_CATEGORIES,
    get_all_rules,
    get_category_rules,
    get_video_specific_rules,
    get_rules_by_check_type,
    get_rules_by_severity,
)

from app.dpdpa.penalty_schedule import (
    PenaltyTier,
    PENALTY_TIERS,
    get_penalty_for_category,
    get_max_penalty_display,
)

"""
PII Definitions Under Indian Data Compliance Framework

India's data protection is primarily governed by:
- Digital Personal Data Protection Act, 2023 (DPDPA)
- IT Act, 2000 + SPDI Rules, 2011

This module defines all PII categories, their regex patterns for OCR detection,
and metadata for compliance reporting.
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class PIIPattern:
    """A single PII detection pattern"""
    name: str                    # e.g., "aadhaar"
    display_name: str            # e.g., "Aadhaar Number"
    category: str                # e.g., "government_id"
    regex: str                   # regex pattern
    description: str             # what this pattern detects
    severity: str = "high"       # high, medium, low
    needs_digit_cleanup: bool = False   # remove OCR-inserted spaces from digits
    min_digits: int = 0          # for digit cleanup validation
    max_digits: int = 0          # for digit cleanup validation
    context_required: bool = False      # needs nearby context words to confirm
    context_words: List[str] = field(default_factory=list)  # words that confirm this PII type


# =============================================================================
# CATEGORY 1: DIRECT IDENTIFIERS
# =============================================================================

DIRECT_IDENTIFIERS = [
    PIIPattern(
        name="name_labeled",
        display_name="Person Name",
        category="direct_identifier",
        regex=r'(?:Name|name|Hi|Hello|Dear|Welcome|Mr\.|Mrs\.|Ms\.|Shri|Smt)[\s:,]+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,}){0,3})',
        description="Full name detected after a label (Name:, Hi, Dear, etc.)",
        severity="high",
    ),
    PIIPattern(
        name="dob",
        display_name="Date of Birth",
        category="direct_identifier",
        regex=r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
        description="Date in DD/MM/YYYY or DD-MM-YYYY format",
        severity="high",
        context_required=True,
        context_words=["dob", "birth", "born", "age", "date of birth"],
    ),
    PIIPattern(
        name="age",
        display_name="Age",
        category="direct_identifier",
        regex=r'(?:age|Age|AGE)[\s:]*(\d{1,3})(?:\s*(?:years?|yrs?|Y))?',
        description="Age value after label",
        severity="medium",
    ),
    PIIPattern(
        name="gender",
        display_name="Gender",
        category="direct_identifier",
        regex=r'(?:Gender|gender|Sex|sex)[\s:]+(?:Male|Female|Other|Trans|M|F)',
        description="Gender after a label",
        severity="medium",
        context_required=True,
        context_words=["gender", "sex", "profile"],
    ),
]


# =============================================================================
# CATEGORY 2: GOVERNMENT IDs
# =============================================================================

GOVERNMENT_IDS = [
    PIIPattern(
        name="aadhaar",
        display_name="Aadhaar Number",
        category="government_id",
        regex=r'\b\d{4}[-\s]\d{4}[-\s]\d{4}\b',
        description="12-digit Aadhaar number in XXXX-XXXX-XXXX format",
        severity="high",
    ),
    PIIPattern(
        name="pan",
        display_name="PAN Card Number",
        category="government_id",
        regex=r'\b[A-Z]{5}\d{4}[A-Z]\b',
        description="10-character PAN in ABCDE1234F format",
        severity="high",
    ),
    PIIPattern(
        name="passport",
        display_name="Passport Number",
        category="government_id",
        regex=r'\b[A-Z]\d{7}\b',
        description="Indian passport: 1 letter + 7 digits",
        severity="high",
        context_required=True,
        context_words=["passport", "travel", "document"],
    ),
    PIIPattern(
        name="voter_id",
        display_name="Voter ID (EPIC)",
        category="government_id",
        regex=r'\b[A-Z]{3}\d{7}\b',
        description="Voter ID / EPIC number: 3 letters + 7 digits",
        severity="high",
        context_required=True,
        context_words=["voter", "epic", "election", "electoral"],
    ),
    PIIPattern(
        name="driving_licence",
        display_name="Driving Licence Number",
        category="government_id",
        regex=r'\b[A-Z]{2}\d{2}\s?\d{4}\s?\d{7}\b',
        description="DL format: state code + issue year + number",
        severity="high",
        context_required=True,
        context_words=["driving", "licence", "license", "dl", "vehicle"],
    ),
]


# =============================================================================
# CATEGORY 3: CONTACT & LOCATION
# =============================================================================

CONTACT_LOCATION = [
    PIIPattern(
        name="phone_india",
        display_name="Phone Number (India)",
        category="contact",
        regex=r'\+?91[-.\s]*[6-9][\d\s-]{9,14}',
        description="Indian phone with +91 prefix (handles OCR spacing)",
        severity="high",
        needs_digit_cleanup=True,
        min_digits=10,
        max_digits=12,
    ),
    PIIPattern(
        name="phone_10digit",
        display_name="Phone Number (10-digit)",
        category="contact",
        regex=r'\b[6-9]\d[\d\s]{8,13}\b',
        description="10-digit Indian mobile number starting with 6-9",
        severity="high",
        needs_digit_cleanup=True,
        min_digits=10,
        max_digits=10,
    ),
    PIIPattern(
        name="phone_intl",
        display_name="Phone Number (International)",
        category="contact",
        regex=r'\+\d{1,3}[-.\s]?\d{4,5}[-.\s]?\d{4,10}',
        description="International phone number with country code",
        severity="high",
    ),
    PIIPattern(
        name="email",
        display_name="Email Address",
        category="contact",
        regex=r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        description="Email address",
        severity="high",
    ),
    PIIPattern(
        name="address_pincode",
        display_name="PIN Code (Address)",
        category="contact",
        regex=r'\b[1-9]\d{5}\b',
        description="6-digit Indian PIN code",
        severity="medium",
        context_required=True,
        context_words=["pin", "zip", "code", "area", "city", "address", "location",
                       "state", "district", "bangalore", "mumbai", "delhi", "chennai",
                       "hyderabad", "kolkata", "pune", "postal"],
    ),
    PIIPattern(
        name="ip_address",
        display_name="IP Address",
        category="contact",
        regex=r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        description="IPv4 address",
        severity="medium",
    ),
    PIIPattern(
        name="gps_coordinates",
        display_name="GPS Coordinates",
        category="contact",
        regex=r'\b\d{1,3}\.\d{4,},\s*\d{1,3}\.\d{4,}\b',
        description="GPS lat/long coordinates",
        severity="high",
    ),
    PIIPattern(
        name="url",
        display_name="URL",
        category="contact",
        regex=r'https?://[^\s]+',
        description="Web URL (may contain tracking/personal data)",
        severity="low",
    ),
]


# =============================================================================
# CATEGORY 4: FINANCIAL DATA
# =============================================================================

FINANCIAL_DATA = [
    PIIPattern(
        name="credit_card",
        display_name="Credit/Debit Card Number",
        category="financial",
        regex=r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
        description="16-digit card number",
        severity="high",
    ),
    PIIPattern(
        name="bank_account",
        display_name="Bank Account Number",
        category="financial",
        regex=r'\b\d{9,18}\b',
        description="9-18 digit bank account number",
        severity="high",
        context_required=True,
        context_words=["account", "bank", "a/c", "savings", "current", "ifsc"],
    ),
    PIIPattern(
        name="ifsc_code",
        display_name="IFSC Code",
        category="financial",
        regex=r'\b[A-Z]{4}0[A-Z0-9]{6}\b',
        description="Bank IFSC code (4 letters + 0 + 6 alphanumeric)",
        severity="medium",
    ),
    PIIPattern(
        name="upi_id",
        display_name="UPI ID",
        category="financial",
        regex=r'\b[A-Za-z0-9._%+-]+@[a-z]{2,}(?:bank|pay|upi|axis|hdfc|icici|sbi|paytm|gpay|phonepe|ybl|oksbi|okicici|okaxis|ibl)\b',
        description="UPI ID (user@bank format)",
        severity="high",
    ),
]


# =============================================================================
# CATEGORY 5: AUTHENTICATION / SENSITIVE
# =============================================================================

AUTHENTICATION = [
    PIIPattern(
        name="otp",
        display_name="OTP / Verification Code",
        category="authentication",
        regex=r'(?:OTP|otp|code|Code|verify|Verify|verification|Verification|PIN|pin)[\s:is]*(\d{4,6})',
        description="4-6 digit OTP or verification code",
        severity="high",
    ),
    PIIPattern(
        name="ssn",
        display_name="SSN (US)",
        category="authentication",
        regex=r'\b\d{3}-\d{2}-\d{4}\b',
        description="US Social Security Number",
        severity="high",
    ),
]


# =============================================================================
# ALL CATEGORIES COMBINED
# =============================================================================

PII_CATEGORIES = {
    "direct_identifier": {
        "display_name": "Direct Identifiers",
        "description": "Name, DOB, Age, Gender, Photo",
        "patterns": DIRECT_IDENTIFIERS,
    },
    "government_id": {
        "display_name": "Government IDs",
        "description": "Aadhaar, PAN, Passport, Voter ID, Driving Licence",
        "patterns": GOVERNMENT_IDS,
    },
    "contact": {
        "display_name": "Contact & Location",
        "description": "Phone, Email, Address, IP, GPS",
        "patterns": CONTACT_LOCATION,
    },
    "financial": {
        "display_name": "Financial Data",
        "description": "Card numbers, Bank account, IFSC, UPI ID",
        "patterns": FINANCIAL_DATA,
    },
    "authentication": {
        "display_name": "Authentication / Sensitive",
        "description": "OTP, Verification codes, SSN",
        "patterns": AUTHENTICATION,
    },
}


def get_all_patterns() -> List[PIIPattern]:
    """Return all PII patterns across all categories"""
    all_patterns = []
    for category in PII_CATEGORIES.values():
        all_patterns.extend(category["patterns"])
    return all_patterns


def get_category_patterns(category: str) -> List[PIIPattern]:
    """Return PII patterns for a specific category"""
    if category in PII_CATEGORIES:
        return PII_CATEGORIES[category]["patterns"]
    return []

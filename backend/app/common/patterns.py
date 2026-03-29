"""
Shared regex patterns for PII and business identifier detection.

Single source of truth used by both the OCR service and the compliance agent.
Keeping patterns here prevents drift between the two and makes updates atomic.

Regex notes:
- PAN: case-insensitive (OCR sometimes returns lowercase). Allows optional single
  space/hyphen between the letter group and digit group, which EasyOCR sometimes
  inserts due to font spacing (e.g. "AAAPA 5055K").
- Aadhaar: separator is optional (12 digits solid also matches).
- Phone: covers 10-digit mobile, +91 prefix, and international prefix forms.
"""
import re
from typing import List

# Personal data under DPDPA Section 2(t)
# Stored as (pattern_string, flags) pairs so each can carry its own compile flags.
_PII_PATTERN_DEFS: list[tuple[str, str, int]] = [
    # (name, pattern, re_flags)
    ("phone_india",  r"\+?91[\s.\-]?[6-9]\d{9}",                           0),
    ("phone_intl",   r"\+\d{1,3}[\s.\-]?\d{4,5}[\s.\-]?\d{4,10}",         0),
    ("phone_10",     r"\b[6-9]\d{9}\b",                                     0),
    ("email",        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", 0),
    ("credit_card",  r"\b\d{4}[\-\s]?\d{4}[\-\s]?\d{4}[\-\s]?\d{4}\b",    0),
    # Aadhaar: 4-4-4 with optional separator (solid 12-digit also valid)
    ("aadhaar",      r"\b\d{4}[\-\s]?\d{4}[\-\s]?\d{4}\b",                 0),
    # PAN: 5 letters + optional space/dash + 4 digits + optional space/dash + 1 letter
    # Case-insensitive because OCR can return lowercase
    ("pan",          r"\b[A-Z]{5}[\s\-]?\d{4}[\s\-]?[A-Z]\b",              re.IGNORECASE),
    ("ip_address",   r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",            0),
    ("dob",          r"\b\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}\b",               0),
    ("url",          r"https?://[^\s]+",                                     0),
]

# Public dict of raw patterns (string form) for callers that build their own regex
PII_PATTERNS: dict[str, str] = {name: pat for name, pat, _ in _PII_PATTERN_DEFS}

# GST: business identifier (not personal data under DPDPA Section 2(t)).
# Unmasked GST in video -> DPDPA-VID-005 (Section 8(4)).
GST_PATTERN = re.compile(
    r"\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b",
    re.IGNORECASE,
)

# Pre-compiled PII patterns for performance (used on every frame)
_COMPILED_PII: list[tuple[str, re.Pattern]] = [
    (name, re.compile(pat, flags)) for name, pat, flags in _PII_PATTERN_DEFS
]


def detect_pii(text: str) -> List[dict]:
    """
    Scan text for PII using all PII_PATTERNS.
    Returns [{type, redacted}] — actual values are never stored.
    """
    if not text:
        return []
    found = []
    for pii_type, compiled in _COMPILED_PII:
        for _ in compiled.findall(text):
            found.append({"type": pii_type, "redacted": True})
    return found


def detect_gst(text: str) -> list:
    """
    Scan text for GST numbers.
    Returns list of raw matches (values logged but not stored in findings).
    """
    if not text:
        return []
    return GST_PATTERN.findall(text)

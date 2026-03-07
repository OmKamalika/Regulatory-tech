"""
DPDPA 2023 + 2025 Rules — Structured Compliance Rule Definitions

Digital Personal Data Protection Act, 2023 (India)
DPDP Rules, 2025 (Implementation Rules)

Each rule is a machine-readable dataclass that maps DPDPA sections/rules
to video compliance check types from the Step 1 pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class DPDPARule:
    """A single DPDPA compliance rule definition"""
    rule_id: str                        # e.g., "DPDPA-S4-001"
    name: str                           # e.g., "Consent Before Processing"
    section_ref: str                    # e.g., "Section 4" or "Rule 3"
    category: str                       # which category this rule belongs to
    requirement_text: str               # full rule description
    severity: str                       # "critical" / "warning" / "info"
    check_types: List[str]              # what to check in video pipeline output
    violation_condition: str            # describes what constitutes a violation
    applicability: str                  # when this rule applies
    penalty_ref: str                    # e.g., "Section 33(d) - up to 150 crore"
    video_specific: bool = False        # is this specifically about video/CCTV
    detection_guidance: str = ""        # hints for the LangGraph compliance agent
    exemptions: List[str] = field(default_factory=list)
    related_rules: List[str] = field(default_factory=list)


# =============================================================================
# CATEGORY 1: CONSENT (Section 4, Rule 3)
# =============================================================================

CONSENT_RULES = [
    DPDPARule(
        rule_id="DPDPA-S4-001",
        name="Consent Before Processing",
        section_ref="Section 4",
        category="consent",
        requirement_text=(
            "Personal data shall not be processed except in accordance with the "
            "provisions of this Act for a lawful purpose for which an individual "
            "has given her consent. Consent must be free, specific, informed, "
            "unconditional and unambiguous with a clear affirmative action."
        ),
        severity="critical",
        check_types=["consent_indicator", "visual_person_detection"],
        violation_condition=(
            "Video contains identifiable persons but no consent indicator "
            "(consent banner, notice, or consent text) is detected in the content."
        ),
        applicability="Any video containing identifiable individuals being processed.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Check if YOLO detects persons in frames. If persons found, look for "
            "consent-related text in OCR output (consent, agree, I accept, terms)."
        ),
        exemptions=["Government processing for benefits (Section 7)", "Medical emergency"],
        related_rules=["DPDPA-S4-002", "DPDPA-R3-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S4-002",
        name="Informed Consent with Notice",
        section_ref="Section 4(1)",
        category="consent",
        requirement_text=(
            "Before seeking consent, the Data Fiduciary must provide a notice to the "
            "Data Principal containing: the personal data to be collected, the purpose "
            "of processing, all rights of the data principal, and identity of the "
            "data fiduciary and processor."
        ),
        severity="critical",
        check_types=["consent_indicator", "ocr_text_detection"],
        violation_condition=(
            "Processing occurs without a prior notice. No privacy notice, terms, "
            "or data collection disclosure is visible or mentioned in the content."
        ),
        applicability="Before any personal data collection or processing begins.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Search OCR text for privacy notice indicators: 'privacy policy', "
            "'data collection', 'we collect', 'your data', 'terms and conditions'."
        ),
        related_rules=["DPDPA-S4-001", "DPDPA-R3-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S4-003",
        name="Consent Specificity",
        section_ref="Section 4(2)",
        category="consent",
        requirement_text=(
            "Consent must be specific to each purpose of processing. Bundled consent "
            "(combining multiple purposes into one consent) is not valid. Each purpose "
            "must have separate, specific consent."
        ),
        severity="warning",
        check_types=["consent_indicator"],
        violation_condition=(
            "A single blanket consent is used for multiple processing purposes "
            "without specifying each purpose separately."
        ),
        applicability="When personal data is processed for multiple purposes.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Check if consent text bundles multiple purposes without separation."
        ),
        related_rules=["DPDPA-S4-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S4-004",
        name="Consent Withdrawal Right",
        section_ref="Section 4(4)",
        category="consent",
        requirement_text=(
            "Data Principals have the right to withdraw consent at any time. "
            "Upon withdrawal, the Data Fiduciary must cease processing and inform "
            "all third parties to cease use. Withdrawal must be as easy as giving consent."
        ),
        severity="critical",
        check_types=["consent_indicator", "metadata_check"],
        violation_condition=(
            "No mechanism for consent withdrawal is provided or visible. "
            "The system does not offer a way for individuals to revoke consent."
        ),
        applicability="All processing based on consent.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Look for withdrawal options in UI: 'withdraw', 'revoke', 'opt out', "
            "'unsubscribe', 'delete my data'."
        ),
        related_rules=["DPDPA-S4-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S4-005",
        name="Facial Recognition Consent",
        section_ref="Section 4 + Section 2(t)",
        category="consent",
        requirement_text=(
            "Facial data constitutes biometric personal data. Processing facial "
            "recognition requires specific, non-bundled consent with a compelling "
            "legitimate purpose. Less intrusive alternatives must be considered "
            "and documented in a DPIA."
        ),
        severity="critical",
        check_types=["visual_face_detection", "consent_indicator"],
        violation_condition=(
            "Video uses or enables facial recognition without explicit, specific "
            "consent for biometric processing. Face data processed without DPIA."
        ),
        applicability="Any video system that processes or stores facial recognition data.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        video_specific=True,
        detection_guidance=(
            "If face detection finds faces in frames, check if specific biometric "
            "consent is documented. Flag if faces are stored/processed without consent."
        ),
        related_rules=["DPDPA-VID-004", "DPDPA-S10-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-R3-001",
        name="Notice Content Requirements",
        section_ref="Rule 3",
        category="consent",
        requirement_text=(
            "The notice to the Data Principal must contain: description of personal "
            "data being collected, purpose of processing, rights available to the "
            "data principal, identity and contact of Data Fiduciary and DPO, "
            "and the complaint filing process."
        ),
        severity="critical",
        check_types=["ocr_text_detection", "consent_indicator"],
        violation_condition=(
            "Notice is incomplete — missing required elements such as purpose, "
            "rights, or contact information of the Data Fiduciary."
        ),
        applicability="When providing notice to data principals before processing.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Analyze OCR text for notice completeness: check for purpose statement, "
            "rights mention, fiduciary identity, contact details."
        ),
        related_rules=["DPDPA-S4-002"],
    ),
    DPDPARule(
        rule_id="DPDPA-R3-002",
        name="Notice in Clear Language",
        section_ref="Rule 3(2)",
        category="consent",
        requirement_text=(
            "The notice must be in clear, plain language. If the Data Principal "
            "is likely to be a child, the notice must be appropriate for their "
            "understanding. Notice must be available in English and 22 scheduled languages."
        ),
        severity="warning",
        check_types=["ocr_text_detection"],
        violation_condition=(
            "Notice uses legal jargon or complex language that a reasonable person "
            "would not understand. No language options provided."
        ),
        applicability="All notices to data principals.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Check readability of notice text. Flag if language is overly complex."
        ),
        related_rules=["DPDPA-R3-001"],
    ),
]


# =============================================================================
# CATEGORY 2: DATA PRINCIPAL RIGHTS (Sections 11-14)
# =============================================================================

DATA_PRINCIPAL_RIGHTS_RULES = [
    DPDPARule(
        rule_id="DPDPA-S11-001",
        name="Right to Access Information",
        section_ref="Section 11",
        category="data_principal_rights",
        requirement_text=(
            "Data Principals have the right to obtain from the Data Fiduciary: "
            "a summary of personal data being processed, the processing activities, "
            "identities of all Data Processors and Data Fiduciaries with whom "
            "data has been shared, and any other information as prescribed."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "No mechanism exists for data principals to access their data or "
            "information about how their data is being processed."
        ),
        applicability="All data fiduciaries processing personal data.",
        penalty_ref="Section 33(e) - up to 100 crore INR",
        detection_guidance=(
            "Check if the system provides data access features: 'view my data', "
            "'download data', 'data request', 'access request'."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S12-001",
        name="Right to Correction and Erasure",
        section_ref="Section 12",
        category="data_principal_rights",
        requirement_text=(
            "Data Principals have the right to correction of inaccurate or "
            "misleading personal data, completion of incomplete data, updating "
            "of personal data, and erasure of personal data that is no longer "
            "necessary for the stated purpose."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "No mechanism for data correction or deletion is available to "
            "data principals. Erasure requests are not honored."
        ),
        applicability="All data fiduciaries processing personal data.",
        penalty_ref="Section 33(e) - up to 100 crore INR",
        detection_guidance=(
            "Check for correction/deletion features: 'edit profile', 'delete account', "
            "'erase data', 'correct information', 'update details'."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S13-001",
        name="Right to Grievance Redressal",
        section_ref="Section 13",
        category="data_principal_rights",
        requirement_text=(
            "Data Fiduciaries must have an accessible and effective grievance "
            "redressal mechanism. Complaints must be addressed within the "
            "prescribed timeline. Escalation to Data Protection Board is available."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "No grievance mechanism exists or complaints are not addressed "
            "within the required timeline."
        ),
        applicability="All data fiduciaries.",
        penalty_ref="Section 33(e) - up to 100 crore INR",
        detection_guidance=(
            "Check for grievance features: 'complaint', 'grievance', 'support', "
            "'contact us', 'report issue'."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S14-001",
        name="Right to Nominate",
        section_ref="Section 14",
        category="data_principal_rights",
        requirement_text=(
            "Data Principals have the right to nominate another individual to "
            "exercise their rights in case of death or incapacity."
        ),
        severity="warning",
        check_types=["metadata_check"],
        violation_condition=(
            "No nomination mechanism is provided for data principals."
        ),
        applicability="All data fiduciaries.",
        penalty_ref="Section 33(e) - up to 100 crore INR",
        detection_guidance=(
            "Check if nomination feature exists: 'nominate', 'nominee', 'authorized person'."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S11-002",
        name="Right to Data Portability",
        section_ref="Section 11",
        category="data_principal_rights",
        requirement_text=(
            "Data Principals have the right to obtain their personal data in a "
            "structured, commonly used, machine-readable format and to transfer "
            "it to another Data Fiduciary."
        ),
        severity="warning",
        check_types=["metadata_check"],
        violation_condition=(
            "No data export or portability mechanism is available."
        ),
        applicability="All data fiduciaries processing personal data.",
        penalty_ref="Section 33(e) - up to 100 crore INR",
        detection_guidance=(
            "Check for export features: 'export data', 'download', 'transfer data'."
        ),
    ),
]


# =============================================================================
# CATEGORY 3: DATA FIDUCIARY OBLIGATIONS (Section 8)
# =============================================================================

DATA_FIDUCIARY_RULES = [
    DPDPARule(
        rule_id="DPDPA-S8-001",
        name="Data Accuracy",
        section_ref="Section 8(3)",
        category="data_fiduciary_obligations",
        requirement_text=(
            "Data Fiduciary shall make reasonable effort to ensure that the "
            "personal data processed is complete, accurate and not misleading, "
            "especially when such data is used for decisions affecting the "
            "Data Principal or disclosed to another Data Fiduciary."
        ),
        severity="warning",
        check_types=["ocr_pii_detection"],
        violation_condition=(
            "Personal data stored or displayed is inaccurate, incomplete, or "
            "misleading. No data validation mechanisms in place."
        ),
        applicability="All personal data processing operations.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check if PII data detected in video appears to be validated or "
            "if there are data quality controls visible."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S8-002",
        name="Security Safeguards",
        section_ref="Section 8(4)",
        category="data_fiduciary_obligations",
        requirement_text=(
            "Data Fiduciary shall protect personal data by taking reasonable "
            "security safeguards to prevent personal data breach. This includes "
            "encryption for data in transit and at rest, access controls, "
            "authentication protocols, and continuous monitoring."
        ),
        severity="critical",
        check_types=["ocr_pii_detection", "metadata_check"],
        violation_condition=(
            "Personal data is visible in plaintext without encryption or masking. "
            "PII is displayed without redaction in video content meant for sharing."
        ),
        applicability="All personal data storage and transmission.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check if PII detected in OCR is masked/redacted or shown in plaintext. "
            "Flag unmasked Aadhaar, PAN, phone numbers visible on screen."
        ),
        related_rules=["DPDPA-VID-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S8-003",
        name="Purpose Limitation",
        section_ref="Section 8(5)",
        category="data_fiduciary_obligations",
        requirement_text=(
            "Personal data shall be processed only for the purpose for which "
            "consent was given or the lawful purpose specified. Data cannot be "
            "repurposed without obtaining fresh consent."
        ),
        severity="critical",
        check_types=["visual_person_detection", "audio_content_analysis"],
        violation_condition=(
            "Personal data is being used for purposes beyond what was originally "
            "consented to. Function creep detected."
        ),
        applicability="All personal data processing.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Evaluate if the video content shows data being used for a purpose "
            "different from what was stated in the consent notice."
        ),
        related_rules=["DPDPA-S5-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S8-004",
        name="Storage Limitation",
        section_ref="Section 8(7)",
        category="data_fiduciary_obligations",
        requirement_text=(
            "Personal data shall not be retained beyond the period necessary "
            "for the stated purpose unless required by law. Data must be erased "
            "when no longer needed."
        ),
        severity="critical",
        check_types=["data_retention", "metadata_check"],
        violation_condition=(
            "Personal data is retained beyond the necessary period. No automatic "
            "erasure mechanism exists."
        ),
        applicability="All stored personal data.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check video metadata for creation dates. If old personal data is "
            "still accessible, flag potential retention violation."
        ),
        related_rules=["DPDPA-S8-R8-001"],
    ),
    DPDPARule(
        rule_id="DPDPA-S8-005",
        name="Breach Notification Obligation",
        section_ref="Section 8(6)",
        category="data_fiduciary_obligations",
        requirement_text=(
            "In the event of a personal data breach, the Data Fiduciary shall "
            "notify the Data Protection Board and each affected Data Principal "
            "in the prescribed manner and timeframe."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "A data breach occurred but affected individuals and the Data "
            "Protection Board were not notified within the required timeframe."
        ),
        applicability="All personal data breaches.",
        penalty_ref="Section 33(b) - up to 200 crore INR",
        detection_guidance=(
            "Check if breach notification mechanisms exist. Flag if PII is "
            "exposed without breach handling procedures."
        ),
        related_rules=["DPDPA-R7-001"],
    ),
]


# =============================================================================
# CATEGORY 4: SIGNIFICANT DATA FIDUCIARY (SDF) OBLIGATIONS (Section 10, Rule 13)
# =============================================================================

SDF_RULES = [
    DPDPARule(
        rule_id="DPDPA-S10-001",
        name="Data Protection Impact Assessment",
        section_ref="Section 10 + Rule 13",
        category="sdf_obligations",
        requirement_text=(
            "Significant Data Fiduciaries must conduct a Data Protection Impact "
            "Assessment (DPIA) before any high-risk processing activity. This "
            "includes large-scale video surveillance, facial recognition, and "
            "processing of sensitive personal data."
        ),
        severity="critical",
        check_types=["visual_person_detection", "visual_face_detection", "ocr_pii_detection"],
        violation_condition=(
            "High-risk processing (facial recognition, mass surveillance, sensitive "
            "data processing) without a documented DPIA."
        ),
        applicability="Significant Data Fiduciaries performing high-risk processing.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        video_specific=True,
        detection_guidance=(
            "If video contains large-scale person detection or facial recognition, "
            "check if a DPIA has been conducted and documented."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-R13-001",
        name="SDF Enhanced Processing Controls",
        section_ref="Rule 13",
        category="sdf_obligations",
        requirement_text=(
            "Significant Data Fiduciaries must implement enhanced security "
            "controls, conduct periodic data audits, and maintain detailed "
            "processing records. Independent audits must be conducted annually."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "No audit trail, no periodic security assessments, or no independent "
            "audit records for significant data processing activities."
        ),
        applicability="Organizations designated as Significant Data Fiduciaries.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check for audit mechanisms and compliance documentation."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-R14-001",
        name="Data Protection Officer Requirement",
        section_ref="Rule 14",
        category="sdf_obligations",
        requirement_text=(
            "Significant Data Fiduciaries must appoint a Data Protection Officer "
            "(DPO) who is based in India. The DPO must be an independent position "
            "reporting to senior management with minimum qualifications."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "No Data Protection Officer appointed despite being a Significant "
            "Data Fiduciary."
        ),
        applicability="Organizations designated as Significant Data Fiduciaries.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check if DPO contact information is mentioned in privacy notices."
        ),
    ),
]


# =============================================================================
# CATEGORY 5: CHILDREN'S DATA (Section 9)
# =============================================================================

CHILDREN_DATA_RULES = [
    DPDPARule(
        rule_id="DPDPA-S9-001",
        name="Parental Consent for Minors",
        section_ref="Section 9(1)",
        category="children_data",
        requirement_text=(
            "Processing personal data of children (under 18 years) requires "
            "verifiable consent from the parent or lawful guardian. The Data "
            "Fiduciary must make reasonable efforts to verify that consent is "
            "given by the parent/guardian."
        ),
        severity="critical",
        check_types=["children_detection", "consent_indicator"],
        violation_condition=(
            "Video contains identifiable children but no verifiable parental "
            "consent mechanism is detected or documented."
        ),
        applicability="Any processing involving personal data of children under 18.",
        penalty_ref="Section 33(c) - up to 200 crore INR",
        video_specific=True,
        detection_guidance=(
            "If persons detected appear to be children (age estimation from context), "
            "check for parental consent indicators."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S9-002",
        name="No Tracking of Children",
        section_ref="Section 9(2)",
        category="children_data",
        requirement_text=(
            "Data Fiduciary shall not undertake tracking or behavioral monitoring "
            "of children or targeted advertising directed at children."
        ),
        severity="critical",
        check_types=["children_detection", "visual_person_detection"],
        violation_condition=(
            "Children are being tracked, monitored, or targeted with "
            "advertising through the video system."
        ),
        applicability="All processing of children's data.",
        penalty_ref="Section 33(c) - up to 200 crore INR",
        video_specific=True,
        detection_guidance=(
            "Flag if video content shows tracking or profiling of individuals "
            "identified as children."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S9-003",
        name="No Detrimental Processing of Children Data",
        section_ref="Section 9(3)",
        category="children_data",
        requirement_text=(
            "Processing of children's personal data must not cause any "
            "detrimental effect on the well-being of the child."
        ),
        severity="critical",
        check_types=["children_detection"],
        violation_condition=(
            "Processing of children's data causes or risks causing harm "
            "to the child's well-being."
        ),
        applicability="All processing of children's personal data.",
        penalty_ref="Section 33(c) - up to 200 crore INR",
        detection_guidance=(
            "Evaluate if any processing of detected children's data could "
            "be detrimental to their well-being."
        ),
    ),
]


# =============================================================================
# CATEGORY 6: DATA RETENTION (Section 8(7), Rule 8)
# =============================================================================

DATA_RETENTION_RULES = [
    DPDPARule(
        rule_id="DPDPA-S8-R8-001",
        name="Retention Period Limit",
        section_ref="Section 8(7) + Rule 8",
        category="data_retention",
        requirement_text=(
            "Personal data must not be retained beyond the period necessary "
            "to serve the purpose for which it was collected. Minimum retention "
            "of processing records is 1 year. Automatic erasure must be "
            "implemented after the retention period expires."
        ),
        severity="critical",
        check_types=["data_retention", "metadata_check"],
        violation_condition=(
            "Personal data is retained indefinitely without a defined retention "
            "period or automatic erasure mechanism."
        ),
        applicability="All stored personal data.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check video metadata timestamps. Flag if personal data is "
            "stored beyond reasonable retention periods."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-CCTV-001",
        name="CCTV Retention Maximum 90 Days",
        section_ref="Section 8(7) + Rule 8 + Industry Practice",
        category="data_retention",
        requirement_text=(
            "CCTV and video surveillance footage containing personal data "
            "should not be retained for more than 90 days unless required "
            "for an ongoing investigation or legal obligation. Clear signage "
            "must inform individuals of the surveillance."
        ),
        severity="critical",
        check_types=["data_retention", "metadata_check"],
        violation_condition=(
            "CCTV/surveillance footage containing identifiable individuals is "
            "retained beyond 90 days without legal justification."
        ),
        applicability="CCTV and video surveillance systems.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        video_specific=True,
        detection_guidance=(
            "Check video creation date against current date. Flag if CCTV "
            "footage with persons is older than 90 days."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S8-R8-002",
        name="Erasure After Purpose Fulfilled",
        section_ref="Section 8(7)",
        category="data_retention",
        requirement_text=(
            "Once the purpose for which personal data was collected has been "
            "fulfilled, or the Data Principal withdraws consent, the Data "
            "Fiduciary must erase the data unless retention is required by law."
        ),
        severity="critical",
        check_types=["data_retention"],
        violation_condition=(
            "Personal data continues to be stored and processed after the "
            "original purpose has been fulfilled and consent withdrawn."
        ),
        applicability="All personal data where purpose has been served.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check if data erasure procedures exist. Flag if purpose is "
            "fulfilled but data persists."
        ),
    ),
]


# =============================================================================
# CATEGORY 7: BREACH NOTIFICATION (Rule 7)
# =============================================================================

BREACH_NOTIFICATION_RULES = [
    DPDPARule(
        rule_id="DPDPA-R7-001",
        name="Breach Notification to Board",
        section_ref="Rule 7",
        category="breach_notification",
        requirement_text=(
            "In the event of a personal data breach, the Data Fiduciary must "
            "notify the Data Protection Board of India promptly. The notification "
            "must include: nature of the breach, personal data affected, "
            "likely impact, and mitigation measures taken."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "A personal data breach occurred but the Data Protection Board "
            "was not notified promptly with required details."
        ),
        applicability="All personal data breaches.",
        penalty_ref="Section 33(b) - up to 200 crore INR",
        detection_guidance=(
            "Check for breach handling procedures and notification mechanisms."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-R7-002",
        name="Breach Notification to Data Principal",
        section_ref="Rule 7(3)",
        category="breach_notification",
        requirement_text=(
            "Each affected Data Principal must be notified of the breach, "
            "including the nature of the breach and measures they can take "
            "to protect themselves."
        ),
        severity="critical",
        check_types=["metadata_check"],
        violation_condition=(
            "Affected individuals were not notified of a data breach."
        ),
        applicability="All personal data breaches affecting individuals.",
        penalty_ref="Section 33(b) - up to 200 crore INR",
        detection_guidance=(
            "Check if individual notification mechanisms exist for breach events."
        ),
    ),
]


# =============================================================================
# CATEGORY 8: CROSS-BORDER TRANSFER (Section 16)
# =============================================================================

CROSS_BORDER_RULES = [
    DPDPARule(
        rule_id="DPDPA-S16-001",
        name="Cross-Border Transfer Restriction",
        section_ref="Section 16",
        category="cross_border",
        requirement_text=(
            "Transfer of personal data outside India is permitted only to "
            "countries or territories notified by the Central Government. "
            "Transfer to restricted countries is prohibited."
        ),
        severity="critical",
        check_types=["cross_border_transfer", "metadata_check"],
        violation_condition=(
            "Personal data is transferred to a country not on the approved "
            "list or to a restricted territory."
        ),
        applicability="Any cross-border transfer of personal data.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        detection_guidance=(
            "Check if video data or extracted PII is being sent to servers "
            "outside India. Flag foreign data transfers."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-S16-002",
        name="Video Cross-Border Transfer Consent",
        section_ref="Section 16 + Section 4",
        category="cross_border",
        requirement_text=(
            "Transfer of video data containing personal data outside India "
            "requires additional, specific consent from the Data Principal "
            "beyond the original processing consent."
        ),
        severity="critical",
        check_types=["cross_border_transfer", "consent_indicator"],
        violation_condition=(
            "Video content with personal data is transferred outside India "
            "without specific cross-border transfer consent."
        ),
        applicability="Cross-border transfer of video containing personal data.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        video_specific=True,
        detection_guidance=(
            "If video with PII is shared internationally, check for specific "
            "cross-border transfer consent."
        ),
    ),
]


# =============================================================================
# CATEGORY 9: PURPOSE LIMITATION (Sections 5, 6)
# =============================================================================

PURPOSE_LIMITATION_RULES = [
    DPDPARule(
        rule_id="DPDPA-S5-001",
        name="Purpose Specification",
        section_ref="Section 5",
        category="purpose_limitation",
        requirement_text=(
            "The Data Fiduciary must clearly specify the purpose for which "
            "personal data is being processed before collection begins. "
            "The purpose must be specific, explicit, and legitimate."
        ),
        severity="critical",
        check_types=["consent_indicator", "ocr_text_detection"],
        violation_condition=(
            "No clear purpose is specified for data processing. The purpose "
            "is vague, overly broad, or not communicated to data principals."
        ),
        applicability="All personal data collection and processing.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        detection_guidance=(
            "Check OCR text for purpose statements. Flag if no clear purpose "
            "is visible in consent/notice text."
        ),
        related_rules=["DPDPA-S8-003"],
    ),
    DPDPARule(
        rule_id="DPDPA-S6-001",
        name="No Function Creep",
        section_ref="Section 6",
        category="purpose_limitation",
        requirement_text=(
            "Personal data collected for one purpose shall not be processed "
            "for a different purpose without obtaining fresh consent. Using "
            "CCTV footage collected for security to build marketing profiles "
            "is a violation."
        ),
        severity="critical",
        check_types=["visual_person_detection", "audio_content_analysis"],
        violation_condition=(
            "Video data collected for one purpose (e.g., security) is being "
            "used for a different purpose (e.g., marketing, profiling) "
            "without fresh consent."
        ),
        applicability="All repurposing of personal data.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        video_specific=True,
        detection_guidance=(
            "Check if video content suggests data is being used for purposes "
            "beyond what was originally consented to."
        ),
        related_rules=["DPDPA-S8-003"],
    ),
]


# =============================================================================
# CATEGORY 10: VIDEO-SPECIFIC PII RULES
# =============================================================================

VIDEO_SPECIFIC_RULES = [
    DPDPARule(
        rule_id="DPDPA-VID-001",
        name="PII Visible in Video Frames",
        section_ref="Section 4 + Section 8",
        category="video_pii",
        requirement_text=(
            "Personal data (phone numbers, email addresses, Aadhaar numbers, "
            "PAN cards, bank details) visible in video frames constitutes "
            "personal data processing. Such data must be redacted, masked, "
            "or consented for before the video is shared or stored."
        ),
        severity="critical",
        check_types=["ocr_pii_detection"],
        violation_condition=(
            "PII (phone, email, Aadhaar, PAN, bank details) is visible in "
            "video frames without redaction or masking, and the video is "
            "shared or stored without appropriate consent."
        ),
        applicability="Any video containing visible personal data.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        video_specific=True,
        detection_guidance=(
            "Run PII regex patterns on all OCR text extracted from frames. "
            "Flag any unmasked phone numbers, emails, Aadhaar, PAN, etc. "
            "Cross-reference with PII definitions in app.pii.definitions."
        ),
        related_rules=["DPDPA-S8-002"],
    ),
    DPDPARule(
        rule_id="DPDPA-VID-002",
        name="PII Spoken in Audio",
        section_ref="Section 4 + Section 8",
        category="video_pii",
        requirement_text=(
            "Personal data spoken in video audio (phone numbers dictated, "
            "names mentioned, addresses given) constitutes personal data "
            "processing and is subject to DPDPA requirements."
        ),
        severity="critical",
        check_types=["audio_pii_detection"],
        violation_condition=(
            "PII is spoken aloud in the audio track (phone numbers, names, "
            "addresses) without consent or redaction."
        ),
        applicability="Any video with audio containing personal data.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        video_specific=True,
        detection_guidance=(
            "Run PII regex patterns on audio transcription text. Flag any "
            "spoken phone numbers, names, addresses, or ID numbers."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-VID-003",
        name="OCR Text as Personal Data",
        section_ref="Section 2(t)",
        category="video_pii",
        requirement_text=(
            "Text extracted from video frames via OCR that can identify an "
            "individual (names, addresses, ID numbers) is classified as "
            "personal data under DPDPA Section 2(t) and must be handled "
            "with all data protection requirements."
        ),
        severity="warning",
        check_types=["ocr_text_detection"],
        violation_condition=(
            "OCR-extracted text containing identifying information is stored "
            "or processed without treating it as personal data."
        ),
        applicability="All text extraction from video content.",
        penalty_ref="Section 33(a) - up to 250 crore INR",
        video_specific=True,
        detection_guidance=(
            "Any OCR text that matches PII patterns must be treated as "
            "personal data with full DPDPA protections."
        ),
    ),
    DPDPARule(
        rule_id="DPDPA-VID-004",
        name="Face as Biometric Data",
        section_ref="Section 2(t)",
        category="video_pii",
        requirement_text=(
            "Facial images and facial recognition data in video constitute "
            "biometric personal data. Processing requires specific consent, "
            "compelling legitimate purpose, and must consider less intrusive "
            "alternatives. A DPIA is mandatory."
        ),
        severity="critical",
        check_types=["visual_face_detection"],
        violation_condition=(
            "Faces detected in video are stored or processed for "
            "identification without specific biometric consent and DPIA."
        ),
        applicability="Any video with detectable faces used for identification.",
        penalty_ref="Section 33(d) - up to 150 crore INR",
        video_specific=True,
        detection_guidance=(
            "If YOLO or face detection identifies faces in frames, flag for "
            "biometric consent requirements. Check if faces are being stored "
            "or matched against databases."
        ),
        related_rules=["DPDPA-S4-005", "DPDPA-S10-001"],
    ),
]


# =============================================================================
# ALL CATEGORIES COMBINED
# =============================================================================

DPDPA_CATEGORIES = {
    "consent": {
        "display_name": "Consent Requirements",
        "description": "Section 4, Rule 3 — Consent before processing, notice, specificity",
        "rules": CONSENT_RULES,
    },
    "data_principal_rights": {
        "display_name": "Data Principal Rights",
        "description": "Sections 11-14 — Access, correction, erasure, grievance, nominate",
        "rules": DATA_PRINCIPAL_RIGHTS_RULES,
    },
    "data_fiduciary_obligations": {
        "display_name": "Data Fiduciary Obligations",
        "description": "Section 8 — Accuracy, security, purpose limitation, retention",
        "rules": DATA_FIDUCIARY_RULES,
    },
    "sdf_obligations": {
        "display_name": "Significant Data Fiduciary Obligations",
        "description": "Section 10, Rule 13-14 — DPIA, DPO, enhanced controls",
        "rules": SDF_RULES,
    },
    "children_data": {
        "display_name": "Children's Data Protection",
        "description": "Section 9 — Parental consent, no tracking, no detrimental processing",
        "rules": CHILDREN_DATA_RULES,
    },
    "data_retention": {
        "display_name": "Data Retention & Erasure",
        "description": "Section 8(7), Rule 8 — Retention limits, CCTV 90 days, erasure",
        "rules": DATA_RETENTION_RULES,
    },
    "breach_notification": {
        "display_name": "Breach Notification",
        "description": "Rule 7 — Notification to Board and Data Principals",
        "rules": BREACH_NOTIFICATION_RULES,
    },
    "cross_border": {
        "display_name": "Cross-Border Transfer",
        "description": "Section 16 — Transfer restrictions, additional consent",
        "rules": CROSS_BORDER_RULES,
    },
    "purpose_limitation": {
        "display_name": "Purpose Limitation",
        "description": "Sections 5, 6 — Purpose specification, no function creep",
        "rules": PURPOSE_LIMITATION_RULES,
    },
    "video_pii": {
        "display_name": "Video-Specific PII Rules",
        "description": "PII in frames, audio, OCR text, face as biometric",
        "rules": VIDEO_SPECIFIC_RULES,
    },
}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_all_rules() -> List[DPDPARule]:
    """Return all DPDPA rules across all categories"""
    all_rules = []
    for category in DPDPA_CATEGORIES.values():
        all_rules.extend(category["rules"])
    return all_rules


def get_category_rules(category: str) -> List[DPDPARule]:
    """Return DPDPA rules for a specific category"""
    if category in DPDPA_CATEGORIES:
        return DPDPA_CATEGORIES[category]["rules"]
    return []


def get_video_specific_rules() -> List[DPDPARule]:
    """Return only video-specific rules"""
    return [rule for rule in get_all_rules() if rule.video_specific]


def get_rules_by_check_type(check_type: str) -> List[DPDPARule]:
    """Return all rules that require a specific check type"""
    return [
        rule for rule in get_all_rules()
        if check_type in rule.check_types
    ]


def get_rules_by_severity(severity: str) -> List[DPDPARule]:
    """Return all rules of a specific severity"""
    return [rule for rule in get_all_rules() if rule.severity == severity]

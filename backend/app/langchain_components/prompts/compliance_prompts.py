"""
LLM prompt templates for the DPDPA compliance agent.
Used in Phase 2 (async) to generate human-readable summaries and recommendations.
"""


FINDING_DESCRIPTION_PROMPT = """You are a DPDPA (Digital Personal Data Protection Act 2023) compliance expert.

A compliance check was run on a video. Below is the technical evidence for one finding:

Rule: {rule_name} ({rule_id})
Section: {section_ref}
Requirement: {requirement_text}
Violation Condition: {violation_condition}
Penalty Reference: {penalty_ref}

Evidence detected in the video:
- Frame: #{frame_number} at timestamp {timestamp}s
- Objects detected: {objects_detected}
- PII found: {pii_found}
- OCR text: {ocr_text}
- Check types triggered: {check_types}
- Similarity score: {similarity_score}

Write a clear, factual finding description (2-3 sentences) that:
1. States what was found in plain language
2. Explains why it violates DPDPA
3. Does NOT use technical jargon

Finding description:"""


RECOMMENDATION_PROMPT = """You are a DPDPA compliance consultant.

A video compliance check found the following violation:
Rule: {rule_name} ({rule_id})
Section: {section_ref}
Finding: {finding_description}
Penalty Risk: {penalty_ref}

Write a concise, actionable recommendation (2-4 bullet points) for how the organization can remediate this violation and become compliant.
Focus on practical steps, not legal definitions.

Recommendations:"""


EXECUTIVE_SUMMARY_PROMPT = """You are writing the executive summary section of a DPDPA compliance report for a video recording.

Video ID: {video_id}
Compliance Score: {compliance_score}/100
Status: {status}
Total Checks: {total_checks}
Passed: {passed_checks}
Failed: {failed_checks}
Critical Violations: {critical_violations}

Violations found:
{violations_summary}

Write a professional executive summary (3-5 sentences) suitable for a compliance officer or legal team. Include:
1. Overall compliance status and score
2. The most serious violations found
3. The key risk (penalty exposure) if not remediated
4. One clear call to action

Do not use bullet points. Write in flowing prose.

Executive Summary:"""

"""
Compliance checker orchestrator.

Responsibilities:
1. Create a ComplianceReport row (status: PENDING_REVIEW)
2. Run the LangGraph agent (Phase 1 — structured findings, ~30s)
3. Optionally trigger Phase 2 LLM narrative via Celery (async)
4. Return the report ID so the API can poll for status
"""
import uuid
from datetime import datetime
from typing import Optional

from app.db.session import SessionLocal
from app.models.compliance_report import ComplianceReport, ComplianceStatus
from app.langchain_components.agents.compliance_agent import run_compliance_check


def check_video_compliance(video_id: str, use_llm: bool = False) -> dict:
    """
    Full compliance check for a video.

    Phase 1 (always, ~30s): Structured rule matching → findings → report saved to PostgreSQL.
    Phase 2 (optional, async): Ollama LLM writes executive_summary (triggered separately).

    Returns:
        dict with report_id, status, compliance_score, findings_count, errors
    """
    db = SessionLocal()
    report_id = str(uuid.uuid4())

    try:
        # Create the report row upfront so the API can return a report_id immediately
        report = ComplianceReport(
            id=report_id,
            video_id=video_id,
            status=ComplianceStatus.PENDING_REVIEW,
            executive_summary="Compliance check in progress...",
        )
        db.add(report)
        db.commit()
    finally:
        db.close()

    # Run Phase 1 — LangGraph pipeline
    final_state = run_compliance_check(
        video_id=video_id,
        report_id=report_id,
        use_llm=use_llm,
    )

    # If Phase 2 LLM requested, schedule it via Celery (optional, non-blocking)
    if use_llm:
        try:
            from app.tasks.compliance_tasks import generate_llm_summary_task
            generate_llm_summary_task.delay(report_id)
        except ImportError:
            pass  # Celery tasks not yet wired — Phase 2 skipped gracefully

    return {
        "report_id": final_state.get("report_id") or report_id,
        "video_id": video_id,
        "status": final_state.get("report_data", {}).get("status", "pending_review"),
        "compliance_score": final_state.get("report_data", {}).get("compliance_score"),
        "total_checks": final_state.get("report_data", {}).get("total_checks", 0),
        "failed_checks": final_state.get("report_data", {}).get("failed_checks", 0),
        "critical_violations": final_state.get("report_data", {}).get("critical_violations", 0),
        "findings_count": len(final_state.get("all_findings", [])),
        "errors": final_state.get("errors", []),
        "audit_entries_count": len(final_state.get("audit_entries", [])),
    }


def get_report_summary(report_id: str) -> Optional[dict]:
    """Fetch a compliance report from PostgreSQL by report_id."""
    db = SessionLocal()
    try:
        from app.models.compliance_report import ComplianceReport, ComplianceFinding
        report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
        if not report:
            return None

        findings = db.query(ComplianceFinding).filter(
            ComplianceFinding.report_id == report_id
        ).all()

        return {
            "report_id": report.id,
            "video_id": report.video_id,
            "status": report.status,
            "compliance_score": report.compliance_score,
            "total_checks": report.total_checks,
            "passed_checks": report.passed_checks,
            "failed_checks": report.failed_checks,
            "critical_violations": report.critical_violations,
            "warnings": report.warnings,
            "executive_summary": report.executive_summary,
            "recommendations": report.recommendations,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "completed_at": report.completed_at.isoformat() if report.completed_at else None,
            "findings": [
                {
                    "id": f.id,
                    "guideline_id": f.guideline_id,
                    "is_violation": f.is_violation,
                    "severity": f.severity,
                    "description": f.description,
                    "recommendation": f.recommendation,
                    "timestamp_start": f.timestamp_start,
                    "timestamp_end": f.timestamp_end,
                    "confidence_score": f.confidence_score,
                    "visual_evidence": f.visual_evidence,
                    "ocr_text_excerpt": f.ocr_text_excerpt,
                    "transcript_excerpt": f.transcript_excerpt,
                }
                for f in findings
            ],
        }
    finally:
        db.close()


def get_audit_trail(report_id: str) -> list:
    """Fetch all audit log entries for a report."""
    db = SessionLocal()
    try:
        from app.models.audit_log import AuditLog
        logs = db.query(AuditLog).filter(
            AuditLog.report_id == report_id
        ).order_by(AuditLog.timestamp).all()

        return [
            {
                "id": log.id,
                "step": log.step,
                "action": log.action,
                "rule_id": log.rule_id,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "duration_ms": log.duration_ms,
                "success": log.success,
                "error_message": log.error_message,
                "input_data": log.input_data,
                "output_data": log.output_data,
            }
            for log in logs
        ]
    finally:
        db.close()

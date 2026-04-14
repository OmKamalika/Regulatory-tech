"""
FastAPI router for DPDPA compliance checking endpoints.

Endpoints:
  POST /api/v1/compliance/check/{video_id}      — Trigger compliance check
  GET  /api/v1/compliance/report/{video_id}     — Get latest report for a video
  GET  /api/v1/compliance/report-by-id/{id}     — Get report by report_id
  GET  /api/v1/compliance/audit/{report_id}     — Full audit trail for a report
  GET  /api/v1/compliance/findings/{report_id}  — All findings with evidence
  POST /api/v1/compliance/purge/{video_id}      — Purge raw data after report complete
  POST /api/v1/compliance/guidelines/reload     — Sync latest DPDPA rules into PostgreSQL + Weaviate
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.services.compliance_checker import (
    check_video_compliance,
    get_report_summary,
    get_audit_trail,
)
from app.services.data_lifecycle import purge_raw_data, get_purge_status
from app.db.session import SessionLocal
from app.models.compliance_report import ComplianceReport

router = APIRouter()


@router.post("/check/{video_id}", summary="Run DPDPA compliance check on a video")
async def run_compliance_check(
    video_id: str,
    use_llm: bool = Query(False, description="Enable Ollama LLM for narrative summary (slower)"),
):
    """
    Trigger a full DPDPA compliance check for a processed video.

    Phase 1 (always): Structured rule matching → findings (~30s).
    Phase 2 (use_llm=true): Ollama generates executive summary (async).

    Requires the video to have already been processed through Step 1 pipeline
    (frame extraction, YOLO detection, OCR, vectorization).
    """
    # Verify video exists
    db = SessionLocal()
    try:
        from app.models.video import Video
        from app.models.frame_analysis import FrameAnalysis
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

        # Guard: if raw frame data is already purged, re-running produces a
        # stage-failure 0% report that shadows the real result. Return the existing
        # report instead of creating a new empty one.
        frame_count = db.query(FrameAnalysis).filter(FrameAnalysis.video_id == video_id).count()
        existing_report = (
            db.query(ComplianceReport)
            .filter(ComplianceReport.video_id == video_id)
            .order_by(ComplianceReport.created_at.asc())
            .first()
        )
    finally:
        db.close()

    if frame_count == 0 and existing_report is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Raw frame data for video {video_id} has already been purged (DPDPA data minimisation). "
                f"A compliance report already exists: report_id={existing_report.id}. "
                f"Use GET /report/{video_id} to retrieve it."
            ),
        )

    result = check_video_compliance(video_id=video_id, use_llm=use_llm)

    if result.get("errors"):
        return {
            **result,
            "message": f"Compliance check completed with {len(result['errors'])} error(s). Check errors field.",
        }

    return {
        **result,
        "message": "Compliance check complete. Use GET /report/{video_id} to see the full report.",
    }


@router.get("/report/{video_id}", summary="Get latest compliance report for a video")
async def get_video_report(video_id: str):
    """Get the most recent compliance report for a video, including all findings."""
    db = SessionLocal()
    try:
        report = (
            db.query(ComplianceReport)
            .filter(ComplianceReport.video_id == video_id)
            .order_by(ComplianceReport.created_at.desc())
            .first()
        )
        if not report:
            raise HTTPException(
                status_code=404,
                detail=f"No compliance report found for video {video_id}. Run POST /check/{video_id} first.",
            )
        report_id = report.id
    finally:
        db.close()

    summary = get_report_summary(report_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Report not found")
    return summary


@router.get("/report-by-id/{report_id}", summary="Get compliance report by report ID")
async def get_report_by_id(report_id: str):
    """Get a specific compliance report by its report_id."""
    summary = get_report_summary(report_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
    return summary


@router.get("/audit/{report_id}", summary="Get full audit trail for a compliance report")
async def get_audit(report_id: str):
    """
    Returns every step taken during the compliance pipeline for this report.
    This is the paper trail that justifies each finding in an audit.
    """
    logs = get_audit_trail(report_id)
    if not logs:
        raise HTTPException(
            status_code=404,
            detail=f"No audit log found for report {report_id}",
        )
    return {
        "report_id": report_id,
        "total_entries": len(logs),
        "audit_trail": logs,
    }


@router.get("/findings/{report_id}", summary="Get all compliance findings with evidence")
async def get_findings(report_id: str, violations_only: bool = Query(False)):
    """
    Returns all compliance findings for a report with full evidence chain.
    Set violations_only=true to see only confirmed violations.
    """
    summary = get_report_summary(report_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    findings = summary.get("findings", [])
    if violations_only:
        findings = [f for f in findings if f.get("is_violation")]

    return {
        "report_id": report_id,
        "total_findings": len(findings),
        "findings": findings,
    }


@router.post("/purge/{video_id}", summary="Purge raw video data after compliance report is complete")
async def purge_video_data(video_id: str, report_id: str = Query(..., description="The completed report ID")):
    """
    Purge raw video artifacts (frames, vectors, transcriptions) after compliance report is done.

    Keeps: compliance_reports, compliance_findings, audit_logs, guidelines.
    Deletes: MinIO video+frames, Weaviate VideoContent vectors, frame_analyses, transcription_segments.

    DPDPA data minimisation principle: don't keep personal data longer than necessary.
    """
    # Verify the report is complete before purging
    db = SessionLocal()
    try:
        report = db.query(ComplianceReport).filter(ComplianceReport.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
        if str(report.video_id) != video_id:
            raise HTTPException(status_code=400, detail="Report does not belong to this video")
    finally:
        db.close()

    result = purge_raw_data(video_id=video_id, report_id=report_id)
    return {
        **result,
        "message": "Raw data purged. Compliance report, findings, and audit logs are preserved.",
    }


@router.get("/purge-status/{video_id}", summary="Check if raw data has been purged for a video")
async def check_purge_status(video_id: str):
    """Returns whether raw data (frame_analyses, transcription_segments) still exists for a video."""
    return get_purge_status(video_id)


@router.post("/guidelines/reload", summary="Sync latest DPDPA rules into PostgreSQL and Weaviate")
async def reload_guidelines(clear_existing: bool = Query(False, description="Wipe and re-insert all rules (use when rule definitions changed)")):
    """
    Upsert DPDPA rule definitions from definitions.py into PostgreSQL and Weaviate.

    - Default (clear_existing=false): only inserts rules that do not yet exist — safe to call
      at any time, e.g. after adding a new rule like DPDPA-VID-005.
    - clear_existing=true: drops all existing DPDPA rules and reloads from scratch — use when
      existing rule text/severity has changed and must be updated.

    Returns stats: total rules, newly inserted, skipped, errors.
    """
    try:
        from app.services.guideline_loader import GuidelineLoader
        loader = GuidelineLoader()
        stats = loader.load_all_rules(clear_existing=clear_existing)
        loader.close()
        return {
            "message": "Guidelines reload complete",
            "clear_existing": clear_existing,
            **stats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Guidelines reload failed: {e}")

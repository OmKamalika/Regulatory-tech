"""
FastAPI router for video upload and status endpoints.

Endpoints:
  POST /api/v1/videos/upload-file  — Upload a video file (multipart) and trigger pipeline
  POST /api/v1/videos/upload       — Register a video by local path and trigger pipeline
  GET  /api/v1/videos/{video_id}/status — Poll processing status + compliance result
  GET  /api/v1/videos/             — List all videos
"""
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus
from app.models.compliance_report import ComplianceReport

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "regvision_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload-file", summary="Upload a video file and trigger full pipeline")
async def upload_video_file(file: UploadFile = File(...)):
    """Accepts a multipart video upload, saves to a temp dir, then runs the pipeline."""
    logger.info("upload-file: received filename=%r content_type=%r", file.filename, file.content_type)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = os.path.splitext(file.filename)[1].lstrip(".").lower()
    allowed = {"mp4", "avi", "mov", "mkv", "webm"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext!r}. Allowed: {sorted(allowed)}")

    video_id = str(uuid.uuid4())
    dest_path = os.path.join(UPLOAD_DIR, f"{video_id}.{ext}")

    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as write_err:
        logger.error("upload-file: failed to write file to %s — %s", dest_path, write_err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save uploaded file: {write_err}")

    file_size = os.path.getsize(dest_path)
    logger.info("upload-file: saved %s (%d bytes) → %s", file.filename, file_size, dest_path)

    from app.config import settings as _settings
    if file_size > _settings.MAX_UPLOAD_SIZE:
        os.remove(dest_path)
        max_gb = _settings.MAX_UPLOAD_SIZE / (1024 ** 3)
        raise HTTPException(status_code=413, detail=f"File exceeds {max_gb:.0f} GB limit.")

    db = SessionLocal()
    try:
        video = Video(
            id=video_id,
            filename=file.filename,
            original_filename=file.filename,
            file_size=file_size,
            format=ext,
            minio_path=dest_path,
            status=VideoStatus.UPLOADED,
            processing_progress=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(video)
        db.commit()
        logger.info("upload-file: video record created video_id=%s", video_id)
    except Exception as db_err:
        logger.error("upload-file: DB insert failed for video_id=%s — %s", video_id, db_err, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Database error: {db_err}")
    finally:
        db.close()

    # Queue the pipeline task — non-fatal if Celery/Redis is down
    task_id = None
    pipeline_warnings = []
    try:
        from app.tasks.video_pipeline import process_video_task
        task = process_video_task.delay(video_id=video_id, video_path=dest_path)
        task_id = task.id
        logger.info("upload-file: pipeline task queued task_id=%s for video_id=%s", task_id, video_id)
    except Exception as celery_err:
        logger.error(
            "upload-file: could not queue pipeline task for video_id=%s — %s. "
            "Is Celery worker running? Start with: celery -A app.celery_app worker --pool=solo -l info",
            video_id, celery_err, exc_info=True,
        )
        pipeline_warnings.append(
            f"Pipeline task could not be queued ({type(celery_err).__name__}: {celery_err}). "
            "Ensure the Celery worker is running: "
            "celery -A app.celery_app worker --pool=solo -l info"
        )

    response = {
        "video_id": video_id,
        "task_id": task_id,
        "status": "queued" if task_id else "uploaded",
        "message": (
            "Pipeline started. Poll /api/v1/videos/{video_id}/status for progress."
            if task_id else
            "File uploaded but pipeline task could not be queued — check worker logs."
        ),
    }
    if pipeline_warnings:
        response["warnings"] = pipeline_warnings
    return response


class VideoUploadRequest(BaseModel):
    video_path: str
    video_id: str = None   # Optional — auto-generated if omitted
    force: bool = False    # If True, delete existing data for this path/video_id and re-process


@router.post("/upload", summary="Register a video by path and trigger full pipeline")
def upload_video(request: VideoUploadRequest):
    """
    Accepts a local file path, creates a Video record, and kicks off the
    full async pipeline (vectorization → DPDPA compliance check).

    Pass `force: true` to delete any existing record for this video_id (or same path)
    and re-run the full pipeline from scratch — useful when OCR or other services
    have been fixed and stale results need to be replaced.

    Returns the video_id to use for status polling.
    """
    path = request.video_path

    # Validate the file exists and is a video
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail=f"File not found: {path}")

    ext = os.path.splitext(path)[1].lstrip(".").lower()
    allowed = {"mp4", "avi", "mov", "mkv", "webm"}
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}. Allowed: {allowed}")

    from app.config import settings as _settings
    file_size = os.path.getsize(path)
    if file_size > _settings.MAX_UPLOAD_SIZE:
        max_gb = _settings.MAX_UPLOAD_SIZE / (1024 ** 3)
        raise HTTPException(
            status_code=413,
            detail=f"File size {file_size / (1024 ** 3):.2f} GB exceeds the {max_gb:.0f} GB limit.",
        )

    video_id = request.video_id or str(uuid.uuid4())
    filename = os.path.basename(path)

    db = SessionLocal()
    try:
        if request.force:
            # Delete by explicit video_id first
            existing_by_id = db.query(Video).filter(Video.id == video_id).first() if request.video_id else None
            # Also find any prior upload of the same file path
            existing_by_path = db.query(Video).filter(Video.minio_path == path).all()

            to_delete = {v.id: v for v in existing_by_path}
            if existing_by_id:
                to_delete[existing_by_id.id] = existing_by_id

            for v in to_delete.values():
                db.delete(v)  # CASCADE removes FrameAnalysis, ComplianceReport, AuditLog, etc.

            if to_delete:
                db.commit()
        else:
            # Reject duplicate video_id (existing behaviour)
            existing = db.query(Video).filter(Video.id == video_id).first()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail=f"video_id '{video_id}' already exists. Use force=true to re-process.",
                )

        video = Video(
            id=video_id,
            filename=filename,
            original_filename=filename,
            file_size=file_size,
            format=ext,
            minio_path=path,          # Using local path as storage reference
            status=VideoStatus.UPLOADED,
            processing_progress=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(video)
        db.commit()
    finally:
        db.close()

    # Queue the pipeline task
    from app.tasks.video_pipeline import process_video_task
    task = process_video_task.delay(video_id=video_id, video_path=path)

    # Warn immediately if OCR cannot read text — user should know before waiting 3+ minutes
    pipeline_warnings = []
    try:
        from app.services.ocr_service import OCRService
        ocr_info = OCRService().get_reader_info()
        if not ocr_info.get("can_read_text", False):
            pipeline_warnings.append(
                f"OCR engine '{ocr_info.get('engine', 'fallback')}' cannot read text. "
                "PII visible on screen (phone numbers, Aadhaar, PAN cards) will NOT be detected. "
                "Install EasyOCR or Tesseract, then re-upload with force=true to get a full report."
            )
    except Exception:
        pass

    response = {
        "video_id": video_id,
        "task_id": task.id,
        "status": "queued",
        "message": "Pipeline started. Poll /api/v1/videos/{video_id}/status for progress.",
    }
    if pipeline_warnings:
        response["warnings"] = pipeline_warnings
    return response


@router.get("/{video_id}/status", summary="Get video processing status and compliance result")
def get_video_status(video_id: str):
    """
    Returns current processing status.
    Once status is 'completed', includes the compliance report summary.
    """
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

        # Per-stage breakdown with actionable status labels
        from app.models.frame_analysis import FrameAnalysis
        from sqlalchemy import func
        frames_total = db.query(func.count(FrameAnalysis.id)).filter(
            FrameAnalysis.video_id == video_id
        ).scalar() or 0
        frames_with_text = db.query(func.count(FrameAnalysis.id)).filter(
            FrameAnalysis.video_id == video_id,
            FrameAnalysis.ocr_text != "",
            FrameAnalysis.ocr_text.isnot(None),
        ).scalar() or 0
        frames_with_persons = db.query(func.count(FrameAnalysis.id)).filter(
            FrameAnalysis.video_id == video_id,
            FrameAnalysis.persons_detected > 0,
        ).scalar() or 0

        ocr_coverage = round(frames_with_text / frames_total, 2) if frames_total else 0

        # After auto-purge, frame_analyses rows are deleted (DPDPA data minimisation).
        # frames_total from the table becomes 0, making OCR look "pending" even though
        # it ran successfully. Use visual_analysis_completed (survives purge) as the
        # authoritative signal when the table is empty but the video is done.
        data_purged = frames_total == 0 and (video.frames_processed or 0) > 0
        ocr_stage_status = (
            "completed" if ocr_coverage > 0.1 else
            "completed" if data_purged and video.visual_analysis_completed else
            "degraded" if frames_total > 0 else
            "pending"
        )

        # frames_total: prefer the count stored on the video record (survives purge).
        # Fall back to live table count only when the stored value is missing.
        frames_total_display = video.frames_processed if video.frames_processed else frames_total

        response = {
            "video_id": video_id,
            "filename": video.original_filename,
            "status": video.status,
            "progress": video.processing_progress,
            "error": video.error_message,
            "created_at": video.created_at,
            "processing_started_at": video.processing_started_at,
            "processing_completed_at": video.processing_completed_at,
            "pipeline_stages": {
                "frame_extraction": {
                    "status": "completed" if video.visual_analysis_completed else "pending",
                    "frames_total": frames_total_display,
                    "persons_detected_in": frames_with_persons,
                },
                "ocr": {
                    "status": ocr_stage_status,
                    "frames_with_text": frames_with_text,
                    "coverage": ocr_coverage,
                    "warning": "OCR read no text — PII detection may be incomplete" if ocr_stage_status == "degraded" else None,
                },
                "transcription": {
                    "status": "completed" if video.transcription_completed else "pending",
                },
                "vectorization": {
                    "status": "completed" if video.vectorization_completed else "pending",
                },
            },
        }

        # Attach compliance summary if available
        if video.status == VideoStatus.COMPLETED:
            report = (
                db.query(ComplianceReport)
                .filter(ComplianceReport.video_id == video_id)
                .order_by(ComplianceReport.created_at.desc())
                .first()
            )
            if report:
                response["compliance"] = {
                    "report_id": report.id,
                    "status": report.status,
                    "compliance_score": report.compliance_score,
                    "total_checks": report.total_checks,
                    "passed_checks": report.passed_checks,
                    "failed_checks": report.failed_checks,
                    "critical_violations": report.critical_violations,
                    "completed_at": report.completed_at,
                }

        return response
    finally:
        db.close()


@router.get("/", summary="List all videos")
def list_videos():
    db = SessionLocal()
    try:
        videos = db.query(Video).order_by(Video.created_at.desc()).limit(50).all()
        return [
            {
                "video_id": v.id,
                "filename": v.original_filename,
                "status": v.status,
                "progress": v.processing_progress,
                "created_at": v.created_at,
            }
            for v in videos
        ]
    finally:
        db.close()

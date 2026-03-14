"""
FastAPI router for video upload and status endpoints.

Endpoints:
  POST /api/v1/videos/upload       — Register a video by local path and trigger pipeline
  GET  /api/v1/videos/{video_id}/status — Poll processing status + compliance result
  GET  /api/v1/videos/             — List all videos
"""
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus
from app.models.compliance_report import ComplianceReport

router = APIRouter()


class VideoUploadRequest(BaseModel):
    video_path: str
    video_id: str = None  # Optional — auto-generated if omitted


@router.post("/upload", summary="Register a video by path and trigger full pipeline")
def upload_video(request: VideoUploadRequest):
    """
    Accepts a local file path, creates a Video record, and kicks off the
    full async pipeline (vectorization → DPDPA compliance check).

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

    video_id = request.video_id or str(uuid.uuid4())
    filename = os.path.basename(path)
    file_size = os.path.getsize(path)

    db = SessionLocal()
    try:
        # Reject duplicate video_id
        existing = db.query(Video).filter(Video.id == video_id).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"video_id '{video_id}' already exists")

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

    return {
        "video_id": video_id,
        "task_id": task.id,
        "status": "queued",
        "message": "Pipeline started. Poll /api/v1/videos/{video_id}/status for progress.",
    }


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

        response = {
            "video_id": video_id,
            "filename": video.original_filename,
            "status": video.status,
            "progress": video.processing_progress,
            "error": video.error_message,
            "created_at": video.created_at,
            "processing_started_at": video.processing_started_at,
            "processing_completed_at": video.processing_completed_at,
            "pipeline": {
                "visual_analysis": video.visual_analysis_completed,
                "ocr": video.ocr_completed,
                "transcription": video.transcription_completed,
                "vectorization": video.vectorization_completed,
                "frames_processed": video.frames_processed,
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

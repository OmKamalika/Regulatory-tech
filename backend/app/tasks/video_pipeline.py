"""
Celery task: full video processing pipeline.

Triggered on upload. Runs sequentially:
  1. VideoContentVectorizer  — frame extraction, YOLO, OCR, audio, embeddings → Weaviate + PostgreSQL
  2. check_video_compliance  — DPDPA rule matching → ComplianceReport
"""
import logging
import os
from datetime import datetime

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus

logger = logging.getLogger(__name__)

# ── Ensure FFmpeg is on PATH regardless of how the worker was started ──────────
_FFMPEG_CANDIDATES = [
    # Installed via our install_ffmpeg.ps1 script
    os.path.join(os.path.expanduser("~"), "ffmpeg"),
    # Common Windows install locations
    r"C:\ffmpeg",
    r"C:\Program Files\ffmpeg",
]

def _ensure_ffmpeg_on_path():
    for base in _FFMPEG_CANDIDATES:
        if not os.path.isdir(base):
            continue
        # Check base dir and common subdirs — avoids slow recursive os.walk
        for subdir in ["", "bin"]:
            candidate = os.path.join(base, subdir) if subdir else base
            exe = os.path.join(candidate, "ffmpeg.exe")
            if os.path.isfile(exe):
                if candidate not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
                    logger.info(f"Added FFmpeg to PATH: {candidate}")
                return
        # Fallback: one level of subdirectory search (handles versioned dirs like ffmpeg-8.0.1-essentials_build/bin)
        for entry in os.scandir(base):
            if not entry.is_dir():
                continue
            bin_path = os.path.join(entry.path, "bin")
            exe = os.path.join(bin_path, "ffmpeg.exe")
            if os.path.isfile(exe):
                if bin_path not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
                    logger.info(f"Added FFmpeg to PATH: {bin_path}")
                return
    logger.warning("FFmpeg not found in known locations — ensure it is on PATH")

_ensure_ffmpeg_on_path()


@celery_app.task(
    bind=True,
    name="tasks.process_video",
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    retry_backoff=True,
)
def process_video_task(self, video_id: str, video_path: str):
    """
    Full pipeline task: vectorize video then run compliance check.

    Args:
        video_id:   UUID of the Video record in PostgreSQL
        video_path: Absolute local path to the video file
    """
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            logger.error(f"Video {video_id} not found in DB")
            return {"error": f"Video {video_id} not found"}

        # Mark as processing
        video.status = VideoStatus.PROCESSING
        video.processing_started_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

    try:
        # ── Step 1: Vectorization ──────────────────────────────────────────
        logger.info(f"[{video_id}] Starting vectorization pipeline")
        self.update_state(state="PROGRESS", meta={"step": "vectorizing", "progress": 10})

        from app.services.video_content_vectorizer import VideoContentVectorizer
        vectorizer = VideoContentVectorizer()
        stats = vectorizer.process_video(
            video_id=video_id,
            video_path=video_path,
        )
        logger.info(f"[{video_id}] Vectorization complete: {stats}")

        # Update progress flags in DB
        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            video.frames_processed = stats.get("frames_processed", 0)
            video.visual_analysis_completed = True
            video.ocr_completed = True
            video.transcription_completed = stats.get("transcription_segments", 0) > 0
            video.vectorization_completed = True
            video.processing_progress = 60
            db.commit()
        finally:
            db.close()

        # ── Step 2: Compliance check ───────────────────────────────────────
        logger.info(f"[{video_id}] Starting compliance check")
        self.update_state(state="PROGRESS", meta={"step": "compliance", "progress": 65})

        from app.services.compliance_checker import check_video_compliance
        compliance_result = check_video_compliance(video_id=video_id, use_llm=False)
        logger.info(f"[{video_id}] Compliance check complete: {compliance_result}")

        # ── Mark completed ─────────────────────────────────────────────────
        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            video.status = VideoStatus.COMPLETED
            video.processing_progress = 100
            video.processing_completed_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        score = compliance_result.get("compliance_score")
        status = str(compliance_result.get("status", "")).upper()
        critical = compliance_result.get("critical_violations", 0)
        report_id = compliance_result.get("report_id", "N/A")
        score_str = f"{score:.1f}/100" if score is not None else "N/A"

        print("\n")
        print("=" * 62)
        print("  ✅  PIPELINE COMPLETE")
        print("=" * 62)
        print(f"  Video ID        : {video_id}")
        print(f"  Report ID       : {report_id}")
        print(f"  Status          : {status}")
        print(f"  Compliance Score: {score_str}")
        print(f"  Critical Issues : {critical}")
        print("=" * 62)
        print("  Run status poll or fetch report for full details.")
        print("=" * 62)
        print("\n")

        return {
            "video_id": video_id,
            "status": "completed",
            "vectorization": stats,
            "compliance": {
                "report_id": report_id,
                "status": compliance_result.get("status"),
                "compliance_score": score,
                "critical_violations": critical,
            },
        }

    except Exception as e:
        logger.exception(f"[{video_id}] Pipeline failed: {e}")
        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.FAILED
                video.error_message = str(e)
                db.commit()
        finally:
            db.close()

        # Notify operator via webhook if configured
        from app.config import settings
        if settings.FAILURE_WEBHOOK_URL:
            try:
                import requests as _req
                _req.post(
                    settings.FAILURE_WEBHOOK_URL,
                    json={"video_id": video_id, "error": str(e), "video_path": video_path},
                    timeout=5,
                )
            except Exception as webhook_err:
                logger.warning("Failure webhook call failed: %s", webhook_err)

        print("\n")
        print("=" * 62)
        print("  ❌  PIPELINE FAILED")
        print("=" * 62)
        print(f"  Video ID : {video_id}")
        print(f"  Error    : {e}")
        print("=" * 62)
        print("\n")
        raise

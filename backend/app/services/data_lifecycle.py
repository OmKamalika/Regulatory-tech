"""
Data lifecycle service — purges raw video data after compliance report is complete.

Per DPDPA requirements, raw personal data should not be kept longer than needed.
After a compliance report is generated, the raw artifacts are deleted:
  - MinIO: original video file + extracted frame JPEGs
  - Weaviate VideoContent: frame vectors
  - PostgreSQL: frame_analyses + transcription_segments rows

What is KEPT forever (legal evidence):
  - compliance_reports
  - compliance_findings (with full evidence chain)
  - audit_logs
  - guidelines (DPDPA reference data)
  - Weaviate Guidelines collection
"""
import time
from datetime import datetime
from typing import Optional

from app.db.session import SessionLocal
from app.models.audit_log import AuditLog, AuditStep


def purge_raw_data(video_id: str, report_id: str) -> dict:
    """
    Delete all raw video artifacts after compliance report is complete.

    Args:
        video_id: The video whose raw data to purge
        report_id: The completed compliance report ID (for audit logging)

    Returns:
        dict with counts of deleted items and any errors
    """
    results = {
        "video_id": video_id,
        "report_id": report_id,
        "deleted": {
            "minio_video": False,
            "minio_frames": 0,
            "weaviate_vectors": 0,
            "frame_analyses": 0,
            "transcription_segments": 0,
        },
        "errors": [],
    }

    # --- 1. Log intent to purge BEFORE deleting anything ---
    db = SessionLocal()
    try:
        audit_start = AuditLog(
            video_id=video_id,
            report_id=report_id,
            step=AuditStep.DATA_PURGED,
            action=f"Starting data purge for video {video_id} — raw artifacts will be deleted, report and audit logs preserved",
            input_data={"video_id": video_id, "report_id": report_id},
            timestamp=datetime.utcnow(),
            success=True,
        )
        db.add(audit_start)
        db.commit()
    finally:
        db.close()

    # --- 2. Delete from MinIO ---
    try:
        from minio import Minio
        from app.config import settings

        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

        # Delete original video file (stored under videos/{video_id}/*)
        video_prefix = f"{video_id}/"
        try:
            objects = list(client.list_objects(settings.MINIO_BUCKET_VIDEOS, prefix=video_prefix, recursive=True))
            for obj in objects:
                client.remove_object(settings.MINIO_BUCKET_VIDEOS, obj.object_name)
            results["deleted"]["minio_video"] = True
        except Exception as e:
            results["errors"].append(f"MinIO video delete error: {e}")

        # Delete extracted frame JPEGs (stored under frames/{video_id}/*)
        frames_prefix = f"{video_id}/"
        try:
            frame_objects = list(client.list_objects(settings.MINIO_BUCKET_FRAMES, prefix=frames_prefix, recursive=True))
            for obj in frame_objects:
                client.remove_object(settings.MINIO_BUCKET_FRAMES, obj.object_name)
            results["deleted"]["minio_frames"] = len(frame_objects)
        except Exception as e:
            results["errors"].append(f"MinIO frames delete error: {e}")

    except ImportError:
        results["errors"].append("MinIO client not available — skipping MinIO purge")
    except Exception as e:
        results["errors"].append(f"MinIO connection error: {e}")

    # --- 3. Delete from Weaviate VideoContent ---
    try:
        from app.services.vector_store import VectorStore
        vs = VectorStore()
        deleted_count = vs.delete_video_content(video_id)
        results["deleted"]["weaviate_vectors"] = deleted_count or 0
    except Exception as e:
        results["errors"].append(f"Weaviate delete error: {e}")

    # --- 4. Delete from PostgreSQL (frame_analyses + transcription_segments) ---
    db = SessionLocal()
    try:
        from app.models.frame_analysis import FrameAnalysis
        from app.models.transcription import TranscriptionSegment

        frame_count = db.query(FrameAnalysis).filter(
            FrameAnalysis.video_id == video_id
        ).delete()
        results["deleted"]["frame_analyses"] = frame_count

        transcript_count = db.query(TranscriptionSegment).filter(
            TranscriptionSegment.video_id == video_id
        ).delete()
        results["deleted"]["transcription_segments"] = transcript_count

        db.commit()
    except Exception as e:
        db.rollback()
        results["errors"].append(f"PostgreSQL delete error: {e}")
    finally:
        db.close()

    # --- 5. Log purge completion ---
    db = SessionLocal()
    try:
        success = len(results["errors"]) == 0
        audit_end = AuditLog(
            video_id=video_id,
            report_id=report_id,
            step=AuditStep.DATA_PURGED,
            action=(
                f"Data purge complete for video {video_id}. "
                f"Deleted: {results['deleted']['frame_analyses']} frame_analyses, "
                f"{results['deleted']['transcription_segments']} transcription_segments, "
                f"{results['deleted']['weaviate_vectors']} Weaviate vectors, "
                f"{results['deleted']['minio_frames']} MinIO frame files. "
                f"Errors: {len(results['errors'])}"
            ),
            output_data=results["deleted"],
            timestamp=datetime.utcnow(),
            success=success,
            error_message="; ".join(results["errors"]) if results["errors"] else None,
        )
        db.add(audit_end)
        db.commit()
    finally:
        db.close()

    return results


def get_purge_status(video_id: str) -> dict:
    """Check whether raw data for a video has been purged."""
    db = SessionLocal()
    try:
        from app.models.frame_analysis import FrameAnalysis
        from app.models.transcription import TranscriptionSegment

        frame_count = db.query(FrameAnalysis).filter(
            FrameAnalysis.video_id == video_id
        ).count()
        transcript_count = db.query(TranscriptionSegment).filter(
            TranscriptionSegment.video_id == video_id
        ).count()

        return {
            "video_id": video_id,
            "raw_data_purged": frame_count == 0 and transcript_count == 0,
            "remaining_frame_analyses": frame_count,
            "remaining_transcription_segments": transcript_count,
        }
    finally:
        db.close()

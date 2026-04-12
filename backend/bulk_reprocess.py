"""
Bulk reprocess all videos through the full pipeline.

Resets each video record and re-queues it through the Celery worker so that
frame extraction, OCR, visual analysis, and compliance check all run again
with the current (fixed) code.

Usage
-----
    # Preview — no changes made:
    python bulk_reprocess.py --dry-run

    # Queue all videos:
    python bulk_reprocess.py

    # Queue only videos with a specific status:
    python bulk_reprocess.py --status failed
    python bulk_reprocess.py --status completed

Requirements
------------
- Celery worker must be running:  .\\start.ps1 worker
- Run from the project root with the venv active, from the backend/ directory.
"""
import sys
import os
import argparse
from pathlib import Path

# Make backend package importable when run as a script
sys.path.insert(0, str(Path(__file__).parent))

from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus
from app.models.frame_analysis import FrameAnalysis
from app.models.transcription import TranscriptionSegment
from app.tasks.video_pipeline import process_video_task


def reset_and_queue(video: Video, db, dry_run: bool) -> str:
    """
    Reset a video record and dispatch it to the Celery pipeline.

    Returns a short status string for the summary table.
    """
    path_ok = os.path.isfile(video.minio_path)
    if not path_ok:
        return f"SKIP  — file not found: {video.minio_path}"

    if dry_run:
        return "DRY-RUN — would queue"

    # Delete stale child rows so the re-run starts clean
    db.query(FrameAnalysis).filter(FrameAnalysis.video_id == video.id).delete()
    db.query(TranscriptionSegment).filter(TranscriptionSegment.video_id == video.id).delete()

    # Reset video back to UPLOADED state
    video.status = VideoStatus.UPLOADED
    video.processing_progress = 0
    video.error_message = None
    video.processing_started_at = None
    video.processing_completed_at = None
    video.frames_processed = 0
    video.visual_analysis_completed = False
    video.ocr_completed = False
    video.transcription_completed = False
    video.vectorization_completed = False

    db.commit()

    # Dispatch through Celery (same path as the upload endpoint)
    process_video_task.delay(video_id=video.id, video_path=video.minio_path)
    return "QUEUED"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bulk reprocess videos through the compliance pipeline."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making any changes.",
    )
    parser.add_argument(
        "--status",
        default="all",
        choices=["all", "uploaded", "processing", "completed", "failed"],
        help="Filter by current video status (default: all).",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Video)
        if args.status != "all":
            q = q.filter(Video.status == args.status)
        videos = q.order_by(Video.created_at).all()

        if not videos:
            print(f"\n  No videos found (status filter: {args.status}).\n")
            return

        width = 90
        print("\n" + "=" * width)
        mode = "  DRY-RUN — no changes will be made" if args.dry_run else "  BULK REPROCESS"
        print(f"  {mode}   ({len(videos)} video(s), status={args.status})")
        print("=" * width)
        print(f"  {'VIDEO ID':<38}  {'FILENAME':<30}  RESULT")
        print("-" * width)

        queued = skipped = 0
        for video in videos:
            result = reset_and_queue(video, db, args.dry_run)
            short_name = (video.original_filename or video.filename or "")[:30]
            print(f"  {video.id:<38}  {short_name:<30}  {result}")
            if "QUEUED" in result or "DRY-RUN" in result:
                queued += 1
            else:
                skipped += 1

        print("=" * width)
        if args.dry_run:
            print(f"  DRY-RUN complete — {queued} would be queued, {skipped} would be skipped.")
            print("  Run without --dry-run to actually queue them.")
        else:
            print(f"  Done — {queued} queued, {skipped} skipped.")
            if queued:
                print("  Monitor progress at http://localhost:5555 (Flower).")
        print("=" * width + "\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()

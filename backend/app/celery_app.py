"""
Celery application instance.
"""
from celery import Celery
from celery.signals import worker_ready
from app.config import settings

celery_app = Celery(
    "regtech",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.video_pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=False,
    worker_prefetch_multiplier=1,  # One task at a time per worker (heavy ML jobs)
)


@worker_ready.connect
def run_startup_checks(**kwargs):
    """
    Runs automatically when the worker starts, before accepting any tasks.
    Prints a clear pass/fail table for every critical dependency.
    If any blocking dependency fails, the worker exits immediately with
    a plain-English message telling you exactly what to fix.
    """
    import subprocess
    import sys

    checks = []       # (name, status, note)
    blocking_failed = []

    def ok(name, note=""):
        checks.append((name, "OK   ✓", note))

    def fail(name, note):
        checks.append((name, "FAIL ✗", note))
        blocking_failed.append(name)

    def warn(name, note):
        checks.append((name, "WARN !", note))

    # ── 1. PostgreSQL ──────────────────────────────────────────────────────
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text as _text
        db = SessionLocal()
        db.execute(_text("SELECT 1"))
        db.close()
        ok("PostgreSQL")
    except Exception as e:
        fail("PostgreSQL", f"Cannot connect: {e}  →  Is Docker running? Try: .\\start.ps1 docker")

    # ── 2. Weaviate ────────────────────────────────────────────────────────
    try:
        import httpx as _httpx
        r = _httpx.get(f"{settings.WEAVIATE_URL}/v1/.well-known/ready", timeout=5.0)
        if r.status_code == 200:
            ok("Weaviate")
        else:
            raise RuntimeError(f"HTTP {r.status_code}")
    except Exception as e:
        fail("Weaviate", f"Cannot connect: {e}  →  Is Docker running? Try: .\\start.ps1 docker")

    # ── 3. FFmpeg ──────────────────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            ok("FFmpeg")
        else:
            raise RuntimeError("non-zero exit")
    except FileNotFoundError:
        fail("FFmpeg", "Not found on PATH  →  Install from https://ffmpeg.org/download.html")
    except Exception as e:
        fail("FFmpeg", str(e))

    # ── 4. YOLO model ──────────────────────────────────────────────────────
    try:
        from app.services.visual_analyzer import VisualAnalyzer
        VisualAnalyzer()
        ok("YOLO", f"model={settings.YOLO_MODEL}")
    except Exception as e:
        fail("YOLO", f"{e}  →  Run: python -c \"from ultralytics import YOLO; YOLO('{settings.YOLO_MODEL}')\"")

    # ── 5. OCR engine (warning only — pipeline runs in degraded mode) ──────
    try:
        from app.services.ocr_service import OCRService
        info = OCRService().get_reader_info()
        if info.get("can_read_text"):
            ok("OCR", f"engine={info['engine']}")
        else:
            warn(
                "OCR",
                f"engine='{info['engine']}' cannot read text — on-screen PII (Aadhaar, PAN, phone) "
                "will NOT be detected. Install EasyOCR or Tesseract to fix.",
            )
    except Exception as e:
        warn("OCR", f"Failed to load: {e}")

    # ── 6. DB schema check — FrameAnalysis ────────────────────────────────
    # Uses SQLAlchemy introspection instead of a test INSERT to avoid
    # triggering the video_id FK constraint with a non-existent UUID.
    try:
        from sqlalchemy import inspect as _inspect
        from app.db.session import engine as _engine
        _inspector = _inspect(_engine)
        _fa_cols = {c["name"] for c in _inspector.get_columns("frame_analyses")}
        _fa_required = {
            "id", "video_id", "frame_number", "timestamp", "minio_path",
            "objects_detected", "faces_detected", "persons_detected",
            "ocr_text", "visual_analysis_completed", "ocr_completed", "vectorized",
        }
        _missing = _fa_required - _fa_cols
        if _missing:
            fail("DB schema (FrameAnalysis)", f"Missing columns: {_missing}  →  Run: alembic upgrade head")
        else:
            ok("DB schema (FrameAnalysis)", "schema OK")
    except Exception as e:
        fail("DB schema (FrameAnalysis)", f"Could not inspect table: {e}  →  Run: alembic upgrade head")

    # ── 7. DB schema check — TranscriptionSegment ─────────────────────────
    try:
        from sqlalchemy import inspect as _inspect2
        from app.db.session import engine as _engine2
        _inspector2 = _inspect2(_engine2)
        _ts_cols = {c["name"] for c in _inspector2.get_columns("transcription_segments")}
        _ts_required = {
            "id", "video_id", "start_time", "end_time", "text",
            "confidence", "weaviate_id", "vectorized",
        }
        _missing2 = _ts_required - _ts_cols
        if _missing2:
            fail("DB schema (Transcription)", f"Missing columns: {_missing2}  →  Run: alembic upgrade head")
        else:
            ok("DB schema (Transcription)", "schema OK")
    except Exception as e:
        fail("DB schema (Transcription)", f"Could not inspect table: {e}  →  Run: alembic upgrade head")

    # ── Print results table ────────────────────────────────────────────────
    width = 62
    print("\n" + "=" * width)
    print("  WORKER STARTUP CHECKS")
    print("=" * width)
    for name, status, note in checks:
        label = f"  {status}  {name:<12}"
        print(label + (f"  {note}" if note else ""))
    print("=" * width)

    if blocking_failed:
        print(f"\n  WORKER REFUSING TO START — fix the above FAIL items first.\n")
        print("  Quick fix checklist:")
        print("    1. Open a terminal and run:  .\\start.ps1 docker")
        print("    2. Wait 30 seconds for containers to be ready")
        print("    3. Then restart the worker:  .\\start.ps1 worker")
        print()
        sys.exit(1)
    else:
        ocr_ok = any("OCR" in c[0] and "OK" in c[1] for c in checks)
        if not ocr_ok:
            print("\n  Worker started in DEGRADED mode.")
            print("  On-screen PII will not be detected until OCR is fixed.")
        else:
            print("\n  All checks passed. Worker is ready to process videos.")
        print("=" * width + "\n")

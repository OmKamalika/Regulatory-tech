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

    # ── 6. DB schema write test — FrameAnalysis ────────────────────────────
    # Catches column mismatches (e.g. NOT NULL without default) before any
    # real video is processed. Inserts a sentinel row then immediately deletes it.
    try:
        import uuid as _uuid
        from app.db.session import SessionLocal as _SL
        from app.models.frame_analysis import FrameAnalysis as _FA
        _db = _SL()
        _sentinel_id = str(_uuid.uuid4())
        _row = _FA(
            id=_sentinel_id,
            video_id="00000000-0000-0000-0000-000000000000",  # non-existent FK — test insert only
            frame_number=0,
            timestamp=0.0,
            minio_path="",
            objects_detected=[],
            persons_detected=0,
            ocr_text="",
            visual_analysis_completed=False,
            ocr_completed=False,
            vectorized=False,
        )
        try:
            _db.add(_row)
            _db.flush()          # send INSERT without committing
            ok("DB schema (FrameAnalysis)", "write test passed")
        except Exception as _e:
            fail("DB schema (FrameAnalysis)", f"Insert failed: {_e}  →  Run: alembic upgrade head")
        finally:
            _db.rollback()       # always roll back — sentinel row must not persist
            _db.close()
    except Exception as e:
        warn("DB schema (FrameAnalysis)", f"Could not run write test: {e}")

    # ── 7. DB schema write test — TranscriptionSegment ────────────────────
    try:
        import uuid as _uuid2
        from app.db.session import SessionLocal as _SL2
        from app.models.transcription import TranscriptionSegment as _TS
        _db2 = _SL2()
        _ts_row = _TS(
            id=str(_uuid2.uuid4()),
            video_id="00000000-0000-0000-0000-000000000000",
            start_time=float(0.0),   # verify Python float (not np.float64) is accepted
            end_time=float(1.0),
            text="__startup_check__",
            vectorized=False,
        )
        try:
            _db2.add(_ts_row)
            _db2.flush()
            ok("DB schema (Transcription)", "write test passed")
        except Exception as _e:
            fail("DB schema (Transcription)", f"Insert failed: {_e}  →  Run: alembic upgrade head")
        finally:
            _db2.rollback()
            _db2.close()
    except Exception as e:
        warn("DB schema (Transcription)", f"Could not run write test: {e}")

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

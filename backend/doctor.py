"""
RegVision System Doctor — pre-flight check for all services, schema, and models.

Run this BEFORE starting the API or worker to catch every known failure mode.
Auto-fixes what it can (MinIO buckets, upload directory).
Exits with code 1 if any blocking issue is found.

Usage
-----
    python doctor.py            # full check
    python doctor.py --fix      # check + auto-fix what is possible
    python doctor.py --quick    # connectivity only (fast, no model loading)
"""
import sys
import os
import argparse
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── Result collector ──────────────────────────────────────────────────────────
results = []
_blockers = []

STATUS_OK    = "OK     ✓"
STATUS_WARN  = "WARN   !"
STATUS_FAIL  = "FAIL   ✗"
STATUS_FIXED = "FIXED  ↻"


def _add(category, name, status, note=""):
    results.append((category, name, status, note))
    if status == STATUS_FAIL:
        _blockers.append(f"{category} / {name}")


def ok(cat, name, note=""):    _add(cat, name, STATUS_OK,    note)
def warn(cat, name, note=""):  _add(cat, name, STATUS_WARN,  note)
def fail(cat, name, note=""):  _add(cat, name, STATUS_FAIL,  note)
def fixed(cat, name, note=""): _add(cat, name, STATUS_FIXED, note)


# ─────────────────────────────────────────────────────────────────────────────
def check_settings():
    try:
        from app.config import settings
        issues = []
        if "change-in-production" in settings.SECRET_KEY:
            issues.append("SECRET_KEY is placeholder")
        if "change-in-production" in settings.JWT_SECRET_KEY:
            issues.append("JWT_SECRET_KEY is placeholder")
        if not settings.API_KEY:
            issues.append("API_KEY not set — endpoints unauthenticated")
        if issues:
            warn("Config", "Security", "  |  ".join(issues))
        else:
            ok("Config", "Security")
        ok("Config", "Settings loaded", f"DEBUG={settings.DEBUG}")
    except Exception as e:
        fail("Config", "Settings", str(e))


def check_postgres():
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        ok("Services", "PostgreSQL", "connection OK")
        return True
    except Exception as e:
        fail("Services", "PostgreSQL", f"{e}  →  Run: .\\start.ps1 docker")
        return False


def check_redis():
    try:
        from app.config import settings
        import redis as _redis
        r = _redis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        r.ping()
        ok("Services", "Redis", "PING OK")
    except Exception as e:
        fail("Services", "Redis", f"{e}  →  Run: .\\start.ps1 docker")


def check_weaviate():
    try:
        from app.config import settings
        import httpx
        r = httpx.get(f"{settings.WEAVIATE_URL}/v1/.well-known/ready", timeout=5.0)
        if r.status_code == 200:
            ok("Services", "Weaviate", "ready")
        else:
            fail("Services", "Weaviate", f"HTTP {r.status_code}  →  Run: .\\start.ps1 docker")
            return
        for col in ("VideoContent", "Guidelines"):
            rc = httpx.get(f"{settings.WEAVIATE_URL}/v1/schema/{col}", timeout=5.0)
            if rc.status_code == 200:
                ok("Weaviate", f"Collection:{col}", "schema exists")
            else:
                warn("Weaviate", f"Collection:{col}",
                     "Missing — POST /api/v1/compliance/guidelines/reload (API must be running)")
    except Exception as e:
        fail("Services", "Weaviate", f"{e}  →  Run: .\\start.ps1 docker")


def check_minio(auto_fix):
    try:
        from app.config import settings
        from minio import Minio
        from minio.error import S3Error
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.list_buckets()
        ok("Services", "MinIO", "connection OK")
        for bucket in [settings.MINIO_BUCKET_VIDEOS,
                       settings.MINIO_BUCKET_FRAMES,
                       settings.MINIO_BUCKET_DOCUMENTS]:
            if client.bucket_exists(bucket):
                ok("MinIO", f"Bucket:{bucket}", "exists")
            elif auto_fix:
                try:
                    client.make_bucket(bucket)
                    fixed("MinIO", f"Bucket:{bucket}", "created automatically")
                except S3Error as e:
                    fail("MinIO", f"Bucket:{bucket}", f"Auto-create failed: {e}")
            else:
                fail("MinIO", f"Bucket:{bucket}",
                     "Missing — rerun with --fix to create automatically")
    except ImportError:
        warn("Services", "MinIO", "minio package not installed")
    except Exception as e:
        fail("Services", "MinIO", f"{e}  →  Run: .\\start.ps1 docker")


def check_ffmpeg():
    import subprocess
    try:
        r = subprocess.run(["ffmpeg", "-version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if r.returncode == 0:
            ok("Tools", "FFmpeg", "found on PATH")
        else:
            fail("Tools", "FFmpeg", "non-zero exit  →  Run: .\\install_ffmpeg.ps1")
    except FileNotFoundError:
        fail("Tools", "FFmpeg", "not on PATH  →  Run: .\\install_ffmpeg.ps1")
    except Exception as e:
        fail("Tools", "FFmpeg", str(e))


def check_upload_dir(auto_fix):
    import tempfile
    upload_dir = os.path.join(tempfile.gettempdir(), "regvision_uploads")
    if os.path.isdir(upload_dir):
        try:
            test = os.path.join(upload_dir, "__doctor__")
            open(test, "w").close()
            os.remove(test)
            ok("File System", "Upload directory", upload_dir)
        except Exception as e:
            fail("File System", "Upload directory", f"Not writable: {e}")
    elif auto_fix:
        try:
            os.makedirs(upload_dir, exist_ok=True)
            fixed("File System", "Upload directory", f"Created: {upload_dir}")
        except Exception as e:
            fail("File System", "Upload directory", f"Cannot create: {e}")
    else:
        warn("File System", "Upload directory",
             f"Does not exist: {upload_dir}  →  rerun with --fix")


def check_db_schema():
    """
    Write-test every pipeline model inside ONE transaction, then roll it all back.
    A dummy Video row is inserted first so FK constraints on child tables pass.
    The rollback removes every sentinel row — nothing persists.
    """
    try:
        from app.db.session import SessionLocal
        from app.models.video import Video, VideoStatus
        from app.models.frame_analysis import FrameAnalysis
        from app.models.transcription import TranscriptionSegment
        from app.models.compliance_report import ComplianceReport, ComplianceStatus

        db = SessionLocal()
        dummy_vid_id = str(uuid.uuid4())
        try:
            # 1. Parent video row (satisfies all FK constraints)
            db.add(Video(
                id=dummy_vid_id,
                filename="__doctor__",
                original_filename="__doctor__",
                file_size=0,
                format="mp4",
                minio_path="__doctor__",
                status=VideoStatus.UPLOADED,
            ))
            db.flush()

            # 2. FrameAnalysis
            try:
                db.add(FrameAnalysis(
                    id=str(uuid.uuid4()), video_id=dummy_vid_id,
                    frame_number=0, timestamp=0.0, minio_path="",
                    objects_detected=[], persons_detected=0, ocr_text="",
                    visual_analysis_completed=False, ocr_completed=False, vectorized=False,
                ))
                db.flush()
                ok("DB Schema", "FrameAnalysis", "write test passed")
            except Exception as e:
                fail("DB Schema", "FrameAnalysis",
                     f"{e}  →  cd backend && alembic upgrade head")

            # 3. TranscriptionSegment
            try:
                db.add(TranscriptionSegment(
                    id=str(uuid.uuid4()), video_id=dummy_vid_id,
                    start_time=float(0.0), end_time=float(1.0),
                    text="__doctor__", vectorized=False,
                ))
                db.flush()
                ok("DB Schema", "TranscriptionSegment", "write test passed")
            except Exception as e:
                fail("DB Schema", "TranscriptionSegment",
                     f"{e}  →  cd backend && alembic upgrade head")

            # 4. ComplianceReport
            try:
                db.add(ComplianceReport(
                    id=str(uuid.uuid4()), video_id=dummy_vid_id,
                    status=ComplianceStatus.PENDING_REVIEW,
                ))
                db.flush()
                ok("DB Schema", "ComplianceReport", "write test passed")
            except Exception as e:
                fail("DB Schema", "ComplianceReport",
                     f"{e}  →  cd backend && alembic upgrade head")

        finally:
            db.rollback()   # removes all sentinel rows — nothing persists
            db.close()

    except Exception as e:
        warn("DB Schema", "Write tests", f"Could not run: {e}")

    # NumPy float cast
    try:
        import numpy as np
        val = float(np.float64(3.14))
        assert type(val) is float
        ok("DB Schema", "NumPy→float cast", "np.float64 safely casts to Python float")
    except ImportError:
        pass
    except Exception as e:
        fail("DB Schema", "NumPy→float cast", str(e))


def check_guidelines():
    try:
        from app.db.session import SessionLocal
        from app.models.guideline import Guideline
        db = SessionLocal()
        try:
            count = db.query(Guideline).filter(Guideline.is_active == True).count()
            if count >= 1:
                ok("Data", "DPDPA Guidelines", f"{count} active rules loaded")
            else:
                fail("Data", "DPDPA Guidelines",
                     "0 rules — POST /api/v1/compliance/guidelines/reload (API must be running)")
        finally:
            db.close()
    except Exception as e:
        warn("Data", "DPDPA Guidelines", f"Could not check: {e}")


def check_ml_models():
    from app.config import settings

    try:
        from app.services.visual_analyzer import VisualAnalyzer
        VisualAnalyzer()
        ok("ML Models", "YOLO", f"model={settings.YOLO_MODEL}")
    except Exception as e:
        fail("ML Models", "YOLO", str(e))

    try:
        from app.services.ocr_service import OCRService
        info = OCRService().get_reader_info()
        if info.get("can_read_text"):
            ok("ML Models", "OCR", f"engine={info['engine']}")
        else:
            warn("ML Models", "OCR",
                 f"engine='{info['engine']}' cannot read text — pip install easyocr")
    except Exception as e:
        warn("ML Models", "OCR", f"Failed to load: {e}")

    try:
        import whisper as _whisper
        _whisper.load_model(settings.WHISPER_MODEL)
        ok("ML Models", "Whisper", f"model={settings.WHISPER_MODEL}")
    except Exception as e:
        fail("ML Models", "Whisper", f"Cannot load '{settings.WHISPER_MODEL}': {e}")

    try:
        from app.services.embedding_service import EmbeddingService
        svc = EmbeddingService()
        dim = svc.get_embedding_dimension()
        ok("ML Models", "Embeddings", f"model={settings.EMBEDDING_MODEL}  dim={dim}")
    except Exception as e:
        fail("ML Models", "Embeddings", str(e))


# ─────────────────────────────────────────────────────────────────────────────
def print_report():
    width = 82
    print("\n" + "=" * width)
    print("  REGVISION SYSTEM DOCTOR")
    print("=" * width)

    current_cat = None
    for cat, name, status, note in results:
        if cat != current_cat:
            print(f"\n  [{cat}]")
            current_cat = cat
        line = f"    {status}  {name}" + (f"  —  {note}" if note else "")
        print(line[:width])

    print("\n" + "=" * width)
    n_ok    = sum(1 for r in results if r[2] == STATUS_OK)
    n_fixed = sum(1 for r in results if r[2] == STATUS_FIXED)
    n_warn  = sum(1 for r in results if r[2] == STATUS_WARN)
    n_fail  = sum(1 for r in results if r[2] == STATUS_FAIL)
    print(f"  {len(results)} checks  |  {n_ok} OK  |  {n_fixed} auto-fixed  |  "
          f"{n_warn} warnings  |  {n_fail} failures")

    if _blockers:
        print(f"\n  BLOCKING FAILURES:")
        for b in _blockers:
            print(f"    ✗  {b}")
        print("\n  Fix all FAIL items, then: .\\start.ps1 worker")
    else:
        print(f"\n  {'Warnings present — see above.' if n_warn else 'All checks passed.'}")
        print("  Ready to start:  .\\start.ps1 worker")
    print("=" * width + "\n")
    return n_fail == 0


def main():
    parser = argparse.ArgumentParser(description="RegVision pre-flight system check.")
    parser.add_argument("--fix",   action="store_true", help="Auto-fix where possible.")
    parser.add_argument("--quick", action="store_true", help="Skip ML model loading.")
    args = parser.parse_args()

    print("\nRunning system checks", end="")
    if args.fix:   print(" [auto-fix ON]", end="")
    if args.quick: print(" [quick mode]", end="")
    print("...\n")

    pg_ok = check_postgres()
    check_settings()
    check_redis()
    check_weaviate()
    check_minio(auto_fix=args.fix)
    check_ffmpeg()
    check_upload_dir(auto_fix=args.fix)

    if pg_ok:
        check_db_schema()
        check_guidelines()

    if not args.quick:
        check_ml_models()

    all_ok = print_report()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

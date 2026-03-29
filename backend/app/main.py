"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.db.session import create_tables
from app.api.deps import verify_api_key

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {settings.APP_NAME}")
    settings.validate_for_production()
    logger.info("Creating database tables...")
    create_tables()
    logger.info("Database tables created successfully")

    yield

    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    description="Video Compliance Checking System using Open Source AI Models",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": "1.0.0",
        "status": "operational"
    }


# Health check endpoints
@app.get("/health")
async def health_check():
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME
    }


@app.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with dependency status.

    pipeline_ready = True means ALL critical dependencies are working and
    the system can process a video end-to-end.

    ocr_can_read_text = True means PII visible on screen (phone numbers,
    Aadhaar, PAN) will be detected. False = compliance reports will miss
    on-screen text violations.
    """
    deps = {}
    blocking_failures = []  # failures that stop the pipeline entirely
    warnings = []           # degraded but pipeline still runs (partially)

    # ── 1. PostgreSQL ────────────────────────────────────────────────────────
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text as _text
        db = SessionLocal()
        db.execute(_text("SELECT 1"))
        db.close()
        deps["database"] = {"status": "healthy"}
    except Exception as e:
        deps["database"] = {"status": "unhealthy", "error": str(e)}
        blocking_failures.append("database")

    # ── 2. Redis (Celery task queue) ─────────────────────────────────────────
    try:
        import redis as _redis
        r = _redis.from_url(settings.REDIS_URL)
        r.ping()
        deps["redis"] = {"status": "healthy"}
    except Exception as e:
        deps["redis"] = {"status": "unhealthy", "error": str(e)}
        blocking_failures.append("redis")

    # ── 3. Weaviate (vector store) ───────────────────────────────────────────
    try:
        import httpx as _httpx
        weaviate_resp = _httpx.get(f"{settings.WEAVIATE_URL}/v1/.well-known/ready", timeout=5.0)
        if weaviate_resp.status_code == 200:
            deps["weaviate"] = {"status": "healthy", "url": settings.WEAVIATE_URL}
        else:
            raise RuntimeError(f"HTTP {weaviate_resp.status_code}")
    except Exception as e:
        deps["weaviate"] = {"status": "unhealthy", "error": str(e)}
        blocking_failures.append("weaviate")

    # ── 4. FFmpeg (required for frame extraction) ────────────────────────────
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5
        )
        if result.returncode == 0:
            deps["ffmpeg"] = {"status": "healthy"}
        else:
            raise RuntimeError("ffmpeg returned non-zero exit code")
    except FileNotFoundError:
        deps["ffmpeg"] = {
            "status": "unhealthy",
            "error": "ffmpeg binary not found on PATH",
            "fix": "Install FFmpeg: https://ffmpeg.org/download.html and ensure it is on your PATH"
        }
        blocking_failures.append("ffmpeg")
    except Exception as e:
        deps["ffmpeg"] = {"status": "unhealthy", "error": str(e)}
        blocking_failures.append("ffmpeg")

    # ── 5. OCR engine ────────────────────────────────────────────────────────
    try:
        from app.services.ocr_service import OCRService
        ocr = OCRService()
        info = ocr.get_reader_info()
        can_read = info.get("can_read_text", False)
        deps["ocr"] = {
            "status": "healthy" if can_read else "degraded",
            "engine": info.get("engine", "unknown"),
            "can_read_text": can_read,
        }
        if not can_read:
            deps["ocr"]["warning"] = (
                "OCR engine is in fallback mode — it can detect WHERE text is but "
                "CANNOT READ it. PII visible on screen (phone numbers, Aadhaar, PAN) "
                "will NOT be detected. Install EasyOCR or Tesseract to fix this."
            )
            warnings.append("ocr_cannot_read_text")
    except Exception as e:
        deps["ocr"] = {"status": "unhealthy", "error": str(e)}
        warnings.append("ocr_unavailable")

    # ── 6. YOLO model (object/person detection) ──────────────────────────────
    try:
        from app.services.visual_analyzer import VisualAnalyzer
        VisualAnalyzer()
        deps["yolo"] = {"status": "healthy", "model": settings.YOLO_MODEL}
    except Exception as e:
        deps["yolo"] = {
            "status": "unhealthy",
            "error": str(e),
            "fix": f"Run: python -c \"from ultralytics import YOLO; YOLO('{settings.YOLO_MODEL}')\" to download the model"
        }
        blocking_failures.append("yolo")

    # ── 7. MinIO (object storage) ─────────────────────────────────────────────
    try:
        from minio import Minio as _Minio
        minio_client = _Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        missing_buckets = [
            b for b in [
                settings.MINIO_BUCKET_VIDEOS,
                settings.MINIO_BUCKET_FRAMES,
                settings.MINIO_BUCKET_DOCUMENTS,
            ]
            if not minio_client.bucket_exists(b)
        ]
        if missing_buckets:
            deps["minio"] = {"status": "degraded", "missing_buckets": missing_buckets}
            warnings.append(f"minio_missing_buckets:{','.join(missing_buckets)}")
        else:
            deps["minio"] = {"status": "healthy"}
    except Exception as e:
        deps["minio"] = {"status": "unhealthy", "error": str(e)}
        warnings.append("minio_unavailable")

    # ── 8. Ollama (optional — Phase 2 narrative summaries only) ─────────────
    try:
        import httpx as _httpx
        ollama_resp = _httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        if ollama_resp.status_code == 200:
            models = ollama_resp.json().get("models", [])
            has_model = any(settings.OLLAMA_MODEL in m.get("name", "") for m in models)
            deps["ollama"] = {
                "status": "healthy" if has_model else "degraded",
                "model_available": has_model,
                "note": "Optional — only needed for Phase 2 narrative summaries",
            }
            if not has_model:
                deps["ollama"]["fix"] = f"docker exec -it regtech_ollama ollama pull {settings.OLLAMA_MODEL}"
        else:
            deps["ollama"] = {"status": "degraded", "note": "Optional — Phase 2 only"}
    except Exception as e:
        deps["ollama"] = {
            "status": "degraded",
            "error": str(e),
            "note": "Optional — Phase 2 narrative summaries will not work, but compliance checks still run",
        }

    # ── Summary ───────────────────────────────────────────────────────────────
    pipeline_ready = len(blocking_failures) == 0
    ocr_can_read = deps.get("ocr", {}).get("can_read_text", False)

    if blocking_failures:
        overall = "not_ready"
        message = (
            f"Pipeline CANNOT run. Fix these first: {', '.join(blocking_failures)}. "
            "See each dependency's 'error' and 'fix' fields above."
        )
    elif warnings:
        overall = "degraded"
        message = (
            "Pipeline can run but with reduced accuracy. "
            + ("OCR cannot read on-screen text — PII detection will be incomplete. " if not ocr_can_read else "")
            + "See warnings above."
        )
    else:
        overall = "ready"
        message = "All systems operational. Pipeline is ready to process videos."

    return {
        "status": overall,
        "pipeline_ready": pipeline_ready,
        "ocr_can_read_text": ocr_can_read,
        "message": message,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
        "dependencies": deps,
    }


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if settings.DEBUG else "An error occurred"
        }
    )


# API routers — all /api/v1 routes require X-API-Key when API_KEY is configured
from app.api.v1.compliance import router as compliance_router
from app.api.v1.videos import router as videos_router

_api_deps = [Depends(verify_api_key)]
app.include_router(videos_router, prefix="/api/v1/videos", tags=["videos"], dependencies=_api_deps)
app.include_router(compliance_router, prefix="/api/v1/compliance", tags=["compliance"], dependencies=_api_deps)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

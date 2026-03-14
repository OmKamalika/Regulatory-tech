"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.db.session import create_tables

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
    """Detailed health check with dependency status"""
    health_status = {
        "status": "healthy",
        "service": settings.APP_NAME,
        "dependencies": {}
    }

    # Check database
    try:
        from app.db.session import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        health_status["dependencies"]["database"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # Check Redis
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        health_status["dependencies"]["redis"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["redis"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # Check MinIO
    try:
        from minio import Minio
        client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        # Check if buckets exist
        buckets_exist = all([
            client.bucket_exists(settings.MINIO_BUCKET_VIDEOS),
            client.bucket_exists(settings.MINIO_BUCKET_FRAMES),
            client.bucket_exists(settings.MINIO_BUCKET_DOCUMENTS)
        ])
        health_status["dependencies"]["minio"] = "healthy" if buckets_exist else "unhealthy: buckets missing"
    except Exception as e:
        health_status["dependencies"]["minio"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # Check Weaviate
    try:
        import weaviate
        client = weaviate.Client(url=settings.WEAVIATE_URL)
        client.schema.get()
        health_status["dependencies"]["weaviate"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["weaviate"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    # Check Ollama
    try:
        import httpx
        response = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5.0)
        if response.status_code == 200:
            models = response.json().get("models", [])
            has_model = any(settings.OLLAMA_MODEL in model.get("name", "") for model in models)
            health_status["dependencies"]["ollama"] = "healthy" if has_model else f"unhealthy: model {settings.OLLAMA_MODEL} not found"
        else:
            health_status["dependencies"]["ollama"] = "unhealthy: API error"
    except Exception as e:
        health_status["dependencies"]["ollama"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"

    return health_status


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


# API routers
from app.api.v1.compliance import router as compliance_router
from app.api.v1.videos import router as videos_router

app.include_router(videos_router, prefix="/api/v1/videos", tags=["videos"])
app.include_router(compliance_router, prefix="/api/v1/compliance", tags=["compliance"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )

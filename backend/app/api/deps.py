"""
FastAPI dependency functions shared across routers.
"""
from fastapi import Header, HTTPException, status
from app.config import settings


async def verify_api_key(x_api_key: str = Header(default="")) -> None:
    """
    Verify the X-API-Key header against the configured API key.

    If API_KEY is not configured (empty string), authentication is skipped —
    this allows local development without any .env setup.

    In production, set API_KEY in your .env file and all /api/v1 routes
    will require the key in the X-API-Key request header.
    """
    if not settings.API_KEY:
        # No key configured — development mode, allow all
        return

    if not x_api_key or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Set X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

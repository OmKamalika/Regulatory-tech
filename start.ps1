# Regtech Video Compliance System - Startup Script
# Usage:
#   .\start.ps1 api       -> starts the API server
#   .\start.ps1 worker    -> starts the Celery worker
#   .\start.ps1 docker    -> starts Docker infrastructure

$env:PYTHONPATH = "$PSScriptRoot\backend"

switch ($args[0]) {
    "api" {
        Write-Host "Starting API server..."
        Set-Location "$PSScriptRoot\backend"
        uvicorn app.main:app --reload --port 8000
    }
    "worker" {
        Write-Host "Starting Celery worker..."
        Set-Location "$PSScriptRoot\backend"
        celery -A app.celery_app worker --loglevel=info --pool=solo
    }
    "docker" {
        Write-Host "Starting Docker services..."
        Set-Location "$PSScriptRoot\docker"
        docker compose up -d
        Set-Location "$PSScriptRoot"
    }
    default {
        Write-Host "Usage: .\start.ps1 [api|worker|docker]"
    }
}

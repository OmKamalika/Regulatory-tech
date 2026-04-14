# Regtech Video Compliance System - Startup Script
# Usage:
#   .\start.ps1 api       -> starts the API server
#   .\start.ps1 worker    -> starts the Celery worker
#   .\start.ps1 docker    -> starts Docker infrastructure

$env:PYTHONPATH = "$PSScriptRoot\backend"

# Resolve the pip that belongs to the same Python uvicorn uses
$uvicornPath = (Get-Command uvicorn -ErrorAction SilentlyContinue).Source
if ($uvicornPath) {
    $pythonDir = Split-Path (Split-Path $uvicornPath)
    $pip313 = Join-Path $pythonDir "Scripts\pip.exe"
} else {
    $pip313 = "pip"
}

# Install backend dependencies if not already installed
$flagFile = "$PSScriptRoot\.deps_installed"
if (-not (Test-Path $flagFile)) {
    Write-Host "Installing backend dependencies using $pip313 ..."
    & $pip313 install -r "$PSScriptRoot\backend\requirements.txt"
    New-Item -ItemType File -Path $flagFile | Out-Null
}

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

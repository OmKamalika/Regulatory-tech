# Backend Setup and Testing Guide

This guide will help you set up and test the Regtech Video Compliance backend.

## Prerequisites

Before starting, ensure you have:

- **Python 3.10+** installed
- **Docker Desktop** installed and running
- **Git** installed
- **NVIDIA GPU** (recommended) with CUDA drivers
- **FFmpeg** installed and in PATH
- **At least 20GB** free disk space (for models)

## Step 1: Start Infrastructure Services

Start all required services using Docker Compose:

```bash
cd docker
docker-compose up -d
```

This will start:
- PostgreSQL (database)
- Redis (task queue)
- Weaviate (vector database)
- MinIO (object storage)
- Ollama (LLM server)

**Verify services are running:**

```bash
docker-compose ps
```

All services should show status as "Up".

## Step 2: Install Ollama Model

Pull the Llama 3.1 model into Ollama:

```bash
# For Windows (PowerShell/CMD):
docker exec -it regtech_ollama ollama pull llama3.1:8b

# For Linux/Mac:
docker exec -it regtech_ollama ollama pull llama3.1:8b
```

This will download the ~4.7GB model (may take 5-10 minutes depending on internet speed).

**Verify model is installed:**

```bash
docker exec -it regtech_ollama ollama list
```

You should see `llama3.1:8b` in the list.

## Step 3: Setup Backend Environment

### 3.1 Create Virtual Environment

```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate it:
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 3.2 Install Dependencies

```bash
# Upgrade pip
python -m pip install --upgrade pip

# Install all dependencies
pip install -r requirements.txt
```

**Note**: This will take 10-20 minutes as it downloads:
- PyTorch (~2GB)
- Transformers models
- Whisper model
- EasyOCR
- YOLO
- Other dependencies

### 3.3 Create .env File

```bash
# Copy example env file
cp ../.env.example .env
```

Edit `.env` if needed (default values should work for local development).

## Step 4: Test Services

Run the service test script to verify everything works:

```bash
python test_services.py
```

This will:
- Check all imports
- Load configuration
- Initialize all AI models (Whisper, YOLO, EasyOCR)
- Test database connection

**Expected output:**
```
✓ FastAPI
✓ SQLAlchemy
✓ Whisper
✓ EasyOCR
✓ Ultralytics (YOLO)
...
✓ Database connection successful
```

**First-time notes:**
- Model downloads may occur (Whisper: ~1.5GB, YOLO: ~6MB, EasyOCR: ~100MB)
- This is normal and only happens once
- Models are cached locally

## Step 5: Start the Backend Server

```bash
# Make sure venv is activated
python -m app.main

# OR use uvicorn directly:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

## Step 6: Test the API

### 6.1 Basic Health Check

Open a new terminal and test:

```bash
# Basic health check
curl http://localhost:8000/health

# Detailed health check
curl http://localhost:8000/health/detailed
```

**Expected response:**
```json
{
  "status": "healthy",
  "service": "Regtech Video Compliance"
}
```

### 6.2 View API Documentation

Open in your browser:
```
http://localhost:8000/docs
```

This shows the interactive Swagger UI with all API endpoints.

## Step 7: Test Individual Services

### Test Frame Extraction

Create a test script `test_frame_extraction.py`:

```python
from app.services.frame_extractor import FrameExtractor
import tempfile

# Initialize extractor
extractor = FrameExtractor()

# Test with a sample video (provide your own video path)
video_path = "path/to/test/video.mp4"

# Get video info
info = extractor.get_video_info(video_path)
print(f"Video Info: {info}")

# Extract frames
with tempfile.TemporaryDirectory() as temp_dir:
    frames = extractor.extract_frames(video_path, temp_dir, max_frames=10)
    print(f"Extracted {len(frames)} frames")
    for frame in frames[:3]:
        print(f"  - Frame {frame.frame_number} at {frame.timestamp:.2f}s")
```

Run:
```bash
python test_frame_extraction.py
```

### Test Audio Transcription

```python
from app.services.audio_transcriber import AudioTranscriber

# Initialize transcriber
transcriber = AudioTranscriber()

# Get model info
info = transcriber.get_model_info()
print(f"Model: {info}")

# Test with sample audio
audio_path = "path/to/test/audio.wav"
result = transcriber.transcribe(audio_path)
print(f"Transcription: {result['text']}")
```

### Test OCR

```python
from app.services.ocr_service import OCRService

# Initialize OCR
ocr = OCRService()

# Test with sample image
image_path = "path/to/test/image.jpg"
results = ocr.extract_text(image_path)
print(f"Found {len(results)} text regions")
for result in results:
    print(f"  - '{result.text}' (confidence: {result.confidence:.2f})")
```

### Test Visual Analysis

```python
from app.services.visual_analyzer import VisualAnalyzer

# Initialize analyzer
analyzer = VisualAnalyzer()

# Analyze image
image_path = "path/to/test/image.jpg"
summary = analyzer.get_summary(image_path)
print(f"Analysis Summary:")
print(f"  Total objects: {summary['total_objects']}")
print(f"  Persons detected: {summary['persons_detected']}")
print(f"  Classes: {summary['class_counts']}")
```

## Troubleshooting

### Issue: Docker services won't start

**Solution:**
```bash
# Stop all services
docker-compose down

# Remove volumes (WARNING: deletes data)
docker-compose down -v

# Start fresh
docker-compose up -d
```

### Issue: Database connection failed

**Check if PostgreSQL is running:**
```bash
docker ps | grep postgres
```

**Check logs:**
```bash
docker logs regtech_postgres
```

### Issue: Model loading fails

**Whisper:**
```bash
# Test manually
python -c "import whisper; model = whisper.load_model('medium'); print('OK')"
```

**YOLO:**
```bash
# Test manually
python -c "from ultralytics import YOLO; model = YOLO('yolov8n.pt'); print('OK')"
```

### Issue: Out of memory

If you get GPU out of memory errors:

1. Use smaller models:
   - Whisper: Change `WHISPER_MODEL=small` in `.env`
   - YOLO: Change `YOLO_MODEL=yolov8n.pt` (nano version)
   - Llama: Use `llama3.1:8b` instead of `70b`

2. Use CPU instead of GPU:
   - Set `gpu=False` when initializing services

## Next Steps

Once the backend is working:

1. **Create API Routes** - Add endpoints for video upload, processing, compliance checks
2. **Implement Celery Tasks** - Background jobs for video processing
3. **Add Vector Store Service** - Weaviate integration for embeddings
4. **Build Guideline Parser** - PDF parsing and structuring
5. **Create LangGraph Agent** - Compliance checking workflow

## Useful Commands

```bash
# Check Docker service health
curl http://localhost:9000/minio/health/live  # MinIO
curl http://localhost:8080/v1/.well-known/ready  # Weaviate

# View Docker logs
docker logs regtech_postgres
docker logs regtech_ollama
docker logs regtech_weaviate

# Access MinIO console
# Open http://localhost:9001 in browser
# Login: minioadmin / minioadmin

# PostgreSQL CLI
docker exec -it regtech_postgres psql -U postgres -d regtech_db

# Redis CLI
docker exec -it regtech_redis redis-cli
```

## Performance Tips

1. **GPU Acceleration**: Ensure CUDA is properly installed for faster processing
2. **Model Caching**: First run will be slow due to downloads; subsequent runs are fast
3. **Batch Processing**: Process multiple frames/images in batches when possible
4. **Resource Limits**: Monitor RAM and GPU memory usage

## Summary

You should now have:
- ✅ Docker services running (PostgreSQL, Redis, Weaviate, MinIO, Ollama)
- ✅ Python environment with all dependencies
- ✅ All AI models loaded and tested
- ✅ FastAPI server running
- ✅ API accessible at http://localhost:8000

**Ready to build the compliance checking system!** 🚀

"""
Quick test script to verify all services can be initialized.
Run this to check if all dependencies are installed correctly.
"""
import sys
import os
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test if all required packages can be imported"""
    print("Testing imports...")

    tests = {
        "FastAPI": lambda: __import__("fastapi"),
        "SQLAlchemy": lambda: __import__("sqlalchemy"),
        "Celery": lambda: __import__("celery"),
        "Redis": lambda: __import__("redis"),
        "MinIO": lambda: __import__("minio"),
        "Weaviate": lambda: __import__("weaviate"),
        "OpenCV": lambda: __import__("cv2"),
        "FFmpeg-python": lambda: __import__("ffmpeg"),
        "Whisper": lambda: __import__("whisper"),
        "EasyOCR": lambda: __import__("easyocr"),
        "Ultralytics (YOLO)": lambda: __import__("ultralytics"),
        "Transformers": lambda: __import__("transformers"),
        "Sentence-Transformers": lambda: __import__("sentence_transformers"),
        "LangChain": lambda: __import__("langchain"),
        "LangGraph": lambda: __import__("langgraph"),
    }

    results = {}
    for name, import_func in tests.items():
        try:
            import_func()
            results[name] = "✓"
            print(f"  ✓ {name}")
        except ImportError as e:
            results[name] = "✗"
            print(f"  ✗ {name} - {str(e)}")

    return all(v == "✓" for v in results.values())


def test_config():
    """Test configuration loading"""
    print("\nTesting configuration...")

    try:
        from app.config import settings
        print(f"  ✓ Config loaded")
        print(f"    - App Name: {settings.APP_NAME}")
        print(f"    - Debug: {settings.DEBUG}")
        print(f"    - Database URL: {settings.DATABASE_URL[:30]}...")
        print(f"    - Whisper Model: {settings.WHISPER_MODEL}")
        print(f"    - YOLO Model: {settings.YOLO_MODEL}")
        print(f"    - Embedding Model: {settings.EMBEDDING_MODEL}")
        return True
    except Exception as e:
        print(f"  ✗ Config failed: {e}")
        return False


def test_services():
    """Test service initialization"""
    print("\nTesting services...")

    # Test Frame Extractor
    try:
        from app.services.frame_extractor import FrameExtractor
        extractor = FrameExtractor()
        print(f"  ✓ FrameExtractor initialized")
    except Exception as e:
        print(f"  ✗ FrameExtractor failed: {e}")

    # Test Audio Transcriber
    try:
        from app.services.audio_transcriber import AudioTranscriber
        print(f"  ⏳ Loading Whisper model (this may take a minute)...")
        transcriber = AudioTranscriber()
        info = transcriber.get_model_info()
        print(f"  ✓ AudioTranscriber initialized - Model: {info['model_size']}, Device: {info['device']}")
    except Exception as e:
        print(f"  ✗ AudioTranscriber failed: {e}")

    # Test OCR Service
    try:
        from app.services.ocr_service import OCRService
        print(f"  ⏳ Loading EasyOCR (this may take a minute)...")
        ocr = OCRService()
        info = ocr.get_reader_info()
        print(f"  ✓ OCRService initialized - Languages: {info['languages']}, GPU: {info['gpu_enabled']}")
    except Exception as e:
        print(f"  ✗ OCRService failed: {e}")

    # Test Visual Analyzer
    try:
        from app.services.visual_analyzer import VisualAnalyzer
        print(f"  ⏳ Loading YOLO model...")
        analyzer = VisualAnalyzer()
        info = analyzer.get_model_info()
        print(f"  ✓ VisualAnalyzer initialized - Model: {info['model_path']}, Device: {info['device']}")
    except Exception as e:
        print(f"  ✗ VisualAnalyzer failed: {e}")


def test_database():
    """Test database connection"""
    print("\nTesting database connection...")

    try:
        from app.db.session import SessionLocal
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        print("  ✓ Database connection successful")
        return True
    except Exception as e:
        print(f"  ✗ Database connection failed: {e}")
        print("    Make sure Docker services are running:")
        print("    cd ../docker && docker-compose up -d")
        return False


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║          Regtech Backend - Service Test                      ║
╚══════════════════════════════════════════════════════════════╝
    """)

    all_passed = True

    # Run tests
    all_passed &= test_imports()
    all_passed &= test_config()
    test_services()  # Don't fail on service tests (they take time to download models)
    all_passed &= test_database()

    print("\n" + "="*60)
    if all_passed:
        print("  ✓ ALL CRITICAL TESTS PASSED")
    else:
        print("  ✗ SOME TESTS FAILED")
    print("="*60)

    print("""
Note: Service tests may fail the first time due to model downloads.
This is normal. Models will be cached for future use.

If database test fails, make sure Docker services are running:
  cd ../docker
  docker-compose up -d
    """)


if __name__ == "__main__":
    main()

"""
Reprocess video with working OCR to capture PII.

This script:
1. Clears old video data from vector database
2. Reprocesses the video with Tesseract OCR enabled
3. Stores updated data with OCR text included
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.video_content_vectorizer import VideoContentVectorizer
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def reprocess_video(video_path: str, video_id: str = "test_video_001"):
    """Reprocess video with working OCR"""

    print("\n" + "="*70)
    print("  REPROCESSING VIDEO WITH TESSERACT OCR")
    print("="*70)

    vectorizer = VideoContentVectorizer()

    # Step 1: Delete old video data
    print(f"\n[1/2] Clearing old data for video: {video_id}")
    deleted_count = vectorizer.vector_store.delete_video_content(video_id)
    print(f"      Deleted {deleted_count} old entries")

    # Step 2: Reprocess with OCR
    print(f"\n[2/2] Reprocessing video with OCR enabled...")
    print(f"      Video: {video_path}")
    print("      This may take a few minutes...")

    stats = vectorizer.process_video(
        video_id=video_id,
        video_path=video_path,
        max_frames=50,
        process_audio=False,  # Skip audio as requested
        process_ocr=True      # ENABLE OCR with Tesseract
    )

    print("\n" + "="*70)
    print("  REPROCESSING COMPLETE!")
    print("="*70)
    print(f"\n  Frames Processed:      {stats['frames_processed']}")
    print(f"  Vector DB Entries:     {stats['vector_store_entries']}")
    print("\n  OCR is now working with Tesseract!")
    print("  Run extract_pii_from_video.py to see all PII detected.\n")
    print("="*70 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reprocess video with working OCR")
    parser.add_argument("video_path", help="Path to video file")
    parser.add_argument("--video-id", default="test_video_001", help="Video ID (default: test_video_001)")

    args = parser.parse_args()

    reprocess_video(args.video_path, args.video_id)

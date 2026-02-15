"""Extract PII from second video"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from extract_pii_from_video import PIIExtractor

if __name__ == "__main__":
    extractor = PIIExtractor()

    print("\n" + "="*70)
    print("  PII EXTRACTION - VIDEO 2")
    print("="*70 + "\n")

    extractor.extract_all_pii("test_video_002")

    print("\n[OK] PII extraction complete for Video 2!\n")

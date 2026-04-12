"""
Standalone OCR tester — verify the OCR engine and PII detection before bulk reprocess.

Runs the exact same OCR service used by the pipeline on any image file(s) you supply,
then shows every text region found, its confidence score, and any PII patterns matched.

Usage
-----
    # Test a single image:
    python test_ocr.py C:/path/to/image.jpg

    # Test multiple images:
    python test_ocr.py C:/path/to/frame1.jpg C:/path/to/frame2.png

    # Test every image in a folder:
    python test_ocr.py C:/path/to/frames_folder/

    # Also write an annotated copy of each image (bounding boxes drawn):
    python test_ocr.py C:/path/to/image.jpg --annotate

Requirements
------------
Run from backend/ with the venv active. No worker or API needed — runs inline.
"""
import sys
import os
import argparse
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
logging.basicConfig(
    level=logging.WARNING,           # suppress noisy model-load logs
    format="%(levelname)s  %(message)s",
)

from app.services.ocr_service import OCRService
from app.common.patterns import _COMPILED_PII, GST_PATTERN

# ── PII scanner (same patterns used by the pipeline) ──────────────────────────
def scan_for_pii(text: str) -> list[dict]:
    """Return list of {type, match} for every PII hit in text."""
    hits = []
    for pii_type, compiled in _COMPILED_PII:
        for match in compiled.findall(text):
            hits.append({"type": pii_type, "match": match})
    for match in GST_PATTERN.findall(text):
        hits.append({"type": "gst", "match": match})
    return hits


# ── Image collector ────────────────────────────────────────────────────────────
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}

def collect_images(paths: list[str]) -> list[Path]:
    images = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for f in sorted(pp.iterdir()):
                if f.suffix.lower() in IMAGE_EXTS:
                    images.append(f)
        elif pp.is_file() and pp.suffix.lower() in IMAGE_EXTS:
            images.append(pp)
        else:
            print(f"  WARNING: not a valid image or folder — skipping: {p}")
    return images


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test OCR engine and PII detection on image files."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Image file(s) or folder(s) to test.",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Write annotated images with bounding boxes drawn (saved as *_ocr.jpg next to originals).",
    )
    args = parser.parse_args()

    # ── Initialise OCR service ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  INITIALISING OCR ENGINE")
    print("=" * 70)
    ocr = OCRService()
    info = ocr.get_reader_info()
    print(f"  Engine        : {info['engine']}")
    print(f"  Languages     : {', '.join(info['languages'])}")
    print(f"  Can read text : {info['can_read_text']}")
    if not info["can_read_text"]:
        print("\n  WARNING: The active OCR engine CANNOT read text.")
        print("  PII detection will not work. Install EasyOCR to fix:")
        print("    pip install easyocr")
        print("=" * 70 + "\n")
        sys.exit(1)

    # ── Collect images ────────────────────────────────────────────────────────
    images = collect_images(args.paths)
    if not images:
        print("\n  No valid image files found.\n")
        sys.exit(1)

    print(f"\n  Found {len(images)} image(s) to test.\n")

    # ── Process each image ────────────────────────────────────────────────────
    total_regions = 0
    total_pii = 0

    for img_path in images:
        width = 70
        print("=" * width)
        print(f"  IMAGE: {img_path.name}")
        print("=" * width)

        if args.annotate:
            results, annotated_path = ocr.extract_text_with_visualization(str(img_path))
            print(f"  Annotated image: {annotated_path}")
        else:
            results = ocr.extract_text(str(img_path))

        if not results:
            print("  No text detected.\n")
            continue

        # Filter out fallback results (engine=fallback, text="")
        readable = [r for r in results if r.text]
        if not readable:
            print("  OCR found region shapes but could not read text (fallback engine).\n")
            continue

        print(f"  Regions found : {len(readable)}")
        print()
        print(f"  {'CONF':>6}  TEXT")
        print(f"  {'-'*6}  {'-'*50}")

        full_text_parts = []
        for r in readable:
            bar = "█" * int(r.confidence * 10) + "░" * (10 - int(r.confidence * 10))
            print(f"  {r.confidence:>5.2f}  {r.text}")
            full_text_parts.append(r.text)

        full_text = " ".join(full_text_parts)
        total_regions += len(readable)

        # ── PII scan ──────────────────────────────────────────────────────────
        pii_hits = scan_for_pii(full_text)
        print()
        if pii_hits:
            print(f"  ⚠  PII DETECTED ({len(pii_hits)} match(es)):")
            for hit in pii_hits:
                redacted = re.sub(r'\d', '*', hit['match'])  # mask digits for display
                print(f"     [{hit['type'].upper():12}]  {redacted}")
            total_pii += len(pii_hits)
        else:
            print("  ✓  No PII patterns detected in this image.")
        print()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  Images tested   : {len(images)}")
    print(f"  Text regions    : {total_regions}")
    print(f"  PII hits total  : {total_pii}")
    if total_pii > 0:
        print()
        print("  ⚠  PII was detected. The pipeline will flag these as violations.")
    else:
        print()
        print("  ✓  No PII found across all test images.")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

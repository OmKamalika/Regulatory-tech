"""
Extract all PII (Personally Identifiable Information) from processed video.

Uses centralized PII definitions from app/pii/definitions.py
based on DPDPA 2023 and Indian compliance framework.

This script:
1. Retrieves all frames from the vector database
2. Extracts OCR text from each frame
3. Detects PII patterns (phone numbers, emails, Aadhaar, PAN, OTP, names, etc.)
4. Creates a comprehensive report with timestamps and categories
"""
import sys
from pathlib import Path
import re
from collections import defaultdict

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.vector_store import VectorStore
from app.pii.definitions import get_all_patterns, PII_CATEGORIES
from weaviate.classes.query import Filter
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class PIIExtractor:
    """Extract PII from video frames stored in vector database"""

    def __init__(self):
        self.vector_store = VectorStore()
        self.pii_patterns = get_all_patterns()

    def get_all_frames(self, video_id: str):
        """Retrieve all frames for a video from vector database"""
        try:
            collection = self.vector_store.client.collections.get("VideoContent")

            response = collection.query.fetch_objects(
                filters=Filter.by_property("video_id").equal(video_id),
                limit=500
            )

            results = []
            for obj in response.objects:
                results.append({
                    'id': str(obj.uuid),
                    'text': obj.properties.get('text', ''),
                    'timestamp': obj.properties.get('timestamp', 0.0),
                    'metadata': {
                        'frame_number': obj.properties.get('frame_number', 'unknown'),
                        'content_type': obj.properties.get('content_type', ''),
                        'video_id': obj.properties.get('video_id', '')
                    }
                })

            logger.info(f"Retrieved {len(results)} frames from vector database")
            return results

        except Exception as e:
            logger.error(f"Error retrieving frames: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    def detect_pii_in_text(self, text: str) -> dict:
        """Detect all PII patterns in text using centralized definitions"""
        findings = defaultdict(list)

        for pattern_def in self.pii_patterns:
            # Check context requirement
            if pattern_def.context_required:
                if not any(w in text.lower() for w in pattern_def.context_words):
                    continue

            matches = re.findall(pattern_def.regex, text, re.IGNORECASE)
            if not matches:
                continue

            # Common words that are NOT names (OCR false positives)
            NOT_NAMES = {
                'enter', 'basic', 'info', 'optional', 'helps', 'create',
                'will', 'appear', 'your', 'the', 'all', 'updates',
                'edit', 'designed', 'sign', 'tap', 'continue', 'next',
                'back', 'done', 'save', 'cancel', 'close', 'open',
                'select', 'choose', 'enable', 'disable', 'allow',
            }

            cleaned = []
            for match in matches:
                value = match.strip()

                # For name patterns, reject if any word is a common UI word
                if pattern_def.name == "name_labeled":
                    words = value.lower().split()
                    if any(w in NOT_NAMES for w in words):
                        continue
                    # Name must have at least one word with 3+ chars
                    if not any(len(w) >= 3 for w in words):
                        continue

                # For patterns needing digit cleanup (phone numbers with OCR spaces)
                if pattern_def.needs_digit_cleanup:
                    digits_only = re.sub(r'[^\d]', '', value)
                    if len(digits_only) == 12 and digits_only.startswith('91'):
                        value = '+91-' + digits_only[2:]
                    elif len(digits_only) == 10 and digits_only[0] in '6789':
                        value = digits_only
                    else:
                        continue  # Not a valid phone number

                cleaned.append(value)

            unique_matches = list(set(cleaned))
            if unique_matches:
                findings[pattern_def.name].extend([
                    {
                        "value": v,
                        "display_name": pattern_def.display_name,
                        "category": pattern_def.category,
                        "severity": pattern_def.severity,
                    }
                    for v in unique_matches
                ])

        return dict(findings)

    def extract_all_pii(self, video_id: str):
        """Extract all PII from video with timestamps"""
        frames = self.get_all_frames(video_id)

        if not frames:
            print("\n[ERROR] No frames found in vector database")
            print("        Make sure the video has been processed first.")
            return

        logger.info(f"Analyzing {len(frames)} frames for PII")

        # Collect PII by type and timestamp
        pii_by_type = defaultdict(list)
        pii_timeline = []

        for frame in frames:
            text = frame.get('text', '')
            timestamp = frame.get('timestamp', 0.0)
            frame_num = frame.get('metadata', {}).get('frame_number', 'unknown')

            if not text:
                continue

            # Extract only the OCR/content part, skip the metadata prefix
            ocr_text = text
            if "Text displayed:" in text:
                ocr_text = text.split("Text displayed:", 1)[1].strip()
            elif text.startswith("At timestamp"):
                continue

            # Detect PII in OCR text only
            pii_found = self.detect_pii_in_text(ocr_text)

            if pii_found:
                for pii_type, detections in pii_found.items():
                    for det in detections:
                        entry = {
                            'value': det['value'],
                            'display_name': det['display_name'],
                            'category': det['category'],
                            'severity': det['severity'],
                            'timestamp': timestamp,
                            'frame': frame_num,
                        }
                        pii_by_type[pii_type].append(entry)
                        pii_timeline.append({**entry, 'type': pii_type})

        self._display_results(pii_by_type, pii_timeline, video_id)

    def _display_results(self, pii_by_type: dict, pii_timeline: list, video_id: str):
        """Display PII extraction results grouped by DPDPA categories"""
        print("\n" + "="*70)
        print("  PII EXTRACTION REPORT (DPDPA 2023 Framework)")
        print("="*70)
        print(f"\nVideo ID: {video_id}")

        if not pii_by_type:
            print("\n[OK] No PII detected in this video")
            print("\nNote: This is GOOD for privacy compliance!")
            return

        total_instances = sum(len(items) for items in pii_by_type.values())
        high_severity = sum(
            1 for items in pii_by_type.values()
            for item in items if item['severity'] == 'high'
        )

        print(f"\n[WARNING] Total PII Types Detected: {len(pii_by_type)}")
        print(f"Total PII Instances: {total_instances}")
        print(f"High Severity Items: {high_severity}")

        # Group by DPDPA category
        print("\n" + "-"*70)
        print("  PII BY DPDPA CATEGORY")
        print("-"*70)

        categories_found = defaultdict(list)
        for pii_type, items in pii_by_type.items():
            if items:
                cat = items[0]['category']
                categories_found[cat].extend(items)

        for cat_key, cat_info in PII_CATEGORIES.items():
            if cat_key not in categories_found:
                continue

            items = categories_found[cat_key]
            print(f"\n  [{cat_info['display_name'].upper()}]")
            print(f"  {cat_info['description']}")

            # Group by unique value within this category
            by_display = defaultdict(list)
            for item in items:
                by_display[item['display_name']].append(item)

            for display_name, occurrences in by_display.items():
                values = list(set(o['value'] for o in occurrences))
                severity = occurrences[0]['severity']
                severity_tag = f"[{severity.upper()}]"

                for value in values:
                    value_occ = [o for o in occurrences if o['value'] == value]
                    timestamps = sorted(set(f"{o['timestamp']:.2f}s" for o in value_occ))
                    ts_str = ", ".join(timestamps[:10])
                    if len(timestamps) > 10:
                        ts_str += f" ... (+{len(timestamps)-10} more)"

                    print(f"\n    {severity_tag} {display_name}: {value}")
                    print(f"         Occurrences: {len(value_occ)}")
                    print(f"         Timestamps: {ts_str}")

        # Timeline view
        print("\n" + "-"*70)
        print("  CHRONOLOGICAL TIMELINE")
        print("-"*70)

        pii_timeline.sort(key=lambda x: x['timestamp'])

        current_time = -1
        for item in pii_timeline:
            if item['timestamp'] != current_time:
                current_time = item['timestamp']
                print(f"\n[{current_time:.2f}s] (Frame {item['frame']})")

            severity_icon = "!!" if item['severity'] == 'high' else "--"
            print(f"   {severity_icon} {item['display_name']}: {item['value']}")

        # Compliance summary
        print("\n" + "="*70)
        print("  [!] DPDPA 2023 COMPLIANCE WARNING")
        print("="*70)
        print("""
This video contains Personally Identifiable Information (PII)
as defined under India's Digital Personal Data Protection Act, 2023.

Recommended actions:
1. Review DPDPA 2023 compliance requirements
2. Ensure proper consent was obtained for data collection
3. Implement data minimization practices
4. Apply redaction/masking if necessary
5. Maintain audit trail of PII access
6. Appoint Data Protection Officer if required

PII Categories Detected:
""")
        for cat_key in sorted(categories_found.keys()):
            cat_name = PII_CATEGORIES[cat_key]['display_name']
            count = len(categories_found[cat_key])
            print(f"  * {cat_name} ({count} instances)")

        print("\n" + "="*70)


def main():
    """Main entry point"""
    import argparse
    parser = argparse.ArgumentParser(description="Extract PII from processed video")
    parser.add_argument("--video-id", default="test_video_001", help="Video ID to analyze")
    args = parser.parse_args()

    print("""
================================================================
    PII EXTRACTION FROM VIDEO (DPDPA 2023 Framework)
================================================================
    """)

    extractor = PIIExtractor()

    print(f"[VIDEO] Extracting PII from video: {args.video_id}")
    print("[...] Searching through all processed frames...\n")

    extractor.extract_all_pii(args.video_id)

    print("\n[OK] PII extraction complete!")
    print("\n[TIP] This information will be used in STEP 3 for compliance checking")
    print("      against DPDPA 2023 guidelines.\n")


if __name__ == "__main__":
    main()

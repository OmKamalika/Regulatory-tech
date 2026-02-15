"""
Extract all PII (Personally Identifiable Information) from processed video.

This script:
1. Retrieves all frames from the vector database
2. Extracts OCR text from each frame
3. Detects PII patterns (phone numbers, emails, names, etc.)
4. Creates a comprehensive report with timestamps
"""
import sys
from pathlib import Path
import re
from collections import defaultdict

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.vector_store import VectorStore
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

        # PII detection patterns
        self.patterns = {
            "phone_india": r'\+?91[-.\s]?[6-9]\d{9}',
            "phone_intl": r'\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "credit_card": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            "aadhaar": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            "pan": r'\b[A-Z]{5}\d{4}[A-Z]\b',
            "ip_address": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
            "url": r'https?://[^\s]+',
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        }

    def get_all_frames(self, video_id: str):
        """Retrieve all frames for a video from vector database"""
        try:
            # Get all objects from VideoContent collection
            collection = self.vector_store.client.collections.get("VideoContent")

            # Query with filter for specific video
            response = collection.query.fetch_objects(
                filters=Filter.by_property("video_id").equal(video_id),
                limit=200
            )

            # Convert to results format
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
        """Detect all PII patterns in text"""
        findings = defaultdict(list)

        for pii_type, pattern in self.patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Deduplicate matches
                unique_matches = list(set(matches))
                findings[pii_type].extend(unique_matches)

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

        # Debug: Look for frames around the timestamp where phone number was found
        logger.info("Looking for frames around 7-11 seconds (where phone was found):")
        target_frames = [f for f in frames if 7.0 <= f.get('timestamp', 0) <= 11.0]
        for frame in target_frames[:10]:
            logger.info(f"  [{frame.get('timestamp'):.2f}s]: {frame.get('text', '')}")

        for frame in frames:
            text = frame.get('text', '')
            timestamp = frame.get('timestamp', 0.0)
            frame_num = frame.get('metadata', {}).get('frame_number', 'unknown')

            if not text:
                continue

            # Detect PII in this frame
            pii_found = self.detect_pii_in_text(text)

            if pii_found:
                for pii_type, values in pii_found.items():
                    for value in values:
                        pii_by_type[pii_type].append({
                            'value': value,
                            'timestamp': timestamp,
                            'frame': frame_num
                        })
                        pii_timeline.append({
                            'type': pii_type,
                            'value': value,
                            'timestamp': timestamp,
                            'frame': frame_num
                        })

        # Display results
        self._display_results(pii_by_type, pii_timeline, video_id)

    def _display_results(self, pii_by_type: dict, pii_timeline: list, video_id: str):
        """Display PII extraction results"""
        print("\n" + "="*70)
        print("  PII EXTRACTION REPORT")
        print("="*70)
        print(f"\nVideo ID: {video_id}")

        if not pii_by_type:
            print("\n[OK] No PII detected in this video")
            print("\nNote: This is GOOD for privacy compliance!")
            return

        print(f"\n[WARNING] Total PII Types Detected: {len(pii_by_type)}")
        print(f"Total PII Instances: {sum(len(items) for items in pii_by_type.values())}")

        # Summary by type
        print("\n" + "-"*70)
        print("  PII SUMMARY BY TYPE")
        print("-"*70)

        for pii_type, items in sorted(pii_by_type.items()):
            print(f"\n>> {pii_type.upper().replace('_', ' ')}")
            print(f"   Count: {len(items)}")

            # Group by unique value
            value_groups = defaultdict(list)
            for item in items:
                value_groups[item['value']].append(item)

            for value, occurrences in value_groups.items():
                print(f"\n   Value: {value}")
                print(f"   Occurrences: {len(occurrences)}")
                print(f"   Timestamps: ", end="")
                timestamps = sorted([f"{o['timestamp']:.2f}s" for o in occurrences])
                print(", ".join(timestamps))

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

            print(f"   - {item['type'].replace('_', ' ').title()}: {item['value']}")

        print("\n" + "="*70)
        print("  [!] PRIVACY COMPLIANCE WARNING")
        print("="*70)
        print("""
This video contains Personally Identifiable Information (PII).

Recommended actions:
1. Review DPDPA 2025 compliance requirements
2. Ensure proper consent was obtained for data collection
3. Implement data minimization practices
4. Apply redaction/masking if necessary
5. Maintain audit trail of PII access

PII Types Detected:
""")

        for pii_type in sorted(pii_by_type.keys()):
            print(f"  * {pii_type.upper().replace('_', ' ')}")

        print("\n" + "="*70)


def main():
    """Main entry point"""
    print("""
================================================================
        PII EXTRACTION FROM VIDEO - STEP 1 COMPLETE
================================================================
    """)

    extractor = PIIExtractor()

    # Default video ID from test
    video_id = "test_video_001"

    print(f"[VIDEO] Extracting PII from video: {video_id}")
    print("[...] Searching through all processed frames...\n")

    extractor.extract_all_pii(video_id)

    print("\n[OK] PII extraction complete!")
    print("\n[TIP] This information will be used in STEP 3 for compliance checking")
    print("      against DPDPA 2025 guidelines.\n")


if __name__ == "__main__":
    main()

"""
OCR service with fallback support.
Tries pytesseract first, falls back to pattern-based text detection.
"""
import logging
from typing import List, Tuple
from dataclasses import dataclass
import numpy as np
import cv2
import re

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Data class for OCR result"""
    text: str
    confidence: float
    bounding_box: List[List[int]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]


class OCRService:
    """
    OCR service with intelligent fallback.

    Priority:
    1. Try pytesseract (if tesseract binary is installed)
    2. Fall back to simple text detection using OpenCV

    For full OCR capability, install Tesseract:
    Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
    """

    def __init__(self, languages: List[str] = None, use_gpu: bool = False):
        """Initialize OCR service"""
        self.languages = languages or ['eng']
        self.use_gpu = use_gpu
        self.ocr_available = False

        # Try to initialize pytesseract
        try:
            import pytesseract

            # Set Tesseract path for Windows
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

            # Test if tesseract is actually installed
            pytesseract.get_tesseract_version()
            self.pytesseract = pytesseract
            self.ocr_available = True
            logger.info("✅ Tesseract OCR initialized successfully")
        except Exception as e:
            logger.warning(f"⚠️  Tesseract not available: {e}")
            logger.warning("OCR will use fallback pattern detection")
            logger.info("To enable full OCR:")
            logger.info("  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
            logger.info("  Then: pip install pytesseract")
            self.ocr_available = False

    def extract_text(
        self,
        image_path: str,
        detail: int = 1,
        paragraph: bool = False
    ) -> List[OCRResult]:
        """
        Extract text from image.

        Args:
            image_path: Path to image file
            detail: Text detection detail level
            paragraph: Whether to combine text into paragraphs

        Returns:
            List of OCRResult objects
        """
        logger.debug(f"Extracting text from: {image_path}")

        if self.ocr_available:
            return self._extract_with_tesseract(image_path)
        else:
            return self._extract_with_fallback(image_path)

    def _extract_with_tesseract(self, image_path: str) -> List[OCRResult]:
        """Extract text using Tesseract OCR"""
        try:
            from PIL import Image

            image = Image.open(image_path)

            # Get detailed data with bounding boxes
            data = self.pytesseract.image_to_data(
                image,
                output_type=self.pytesseract.Output.DICT
            )

            ocr_results = []
            n_boxes = len(data['text'])

            for i in range(n_boxes):
                text = data['text'][i].strip()
                conf = float(data['conf'][i])

                # Skip empty text or low confidence
                if not text or conf < 0:
                    continue

                # Get bounding box coordinates
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]

                # Convert to our format: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                bbox = [
                    [x, y],
                    [x + w, y],
                    [x + w, y + h],
                    [x, y + h]
                ]

                ocr_results.append(OCRResult(
                    text=text,
                    confidence=conf / 100.0,  # Normalize to 0-1
                    bounding_box=bbox
                ))

            logger.debug(f"Tesseract extracted {len(ocr_results)} text regions")
            return ocr_results

        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")
            return self._extract_with_fallback(image_path)

    def _extract_with_fallback(self, image_path: str) -> List[OCRResult]:
        """
        Fallback method using OpenCV text detection.
        Detects text regions but cannot read the actual text.
        """
        try:
            image = cv2.imread(image_path)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            # Use threshold to detect potential text regions
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)

            # Find contours (potential text regions)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            ocr_results = []

            # Look for rectangular regions that might contain text
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)

                # Filter by size (text regions are usually certain dimensions)
                if w > 20 and h > 10 and w < image.shape[1] * 0.8 and h < image.shape[0] * 0.8:
                    bbox = [
                        [x, y],
                        [x + w, y],
                        [x + w, y + h],
                        [x, y + h]
                    ]

                    # Extract the region
                    roi = gray[y:y+h, x:x+w]

                    # Try to detect if it looks like text (has some pattern)
                    mean_val = np.mean(roi)
                    std_val = np.std(roi)

                    # Text regions usually have some variation
                    if std_val > 20:
                        ocr_results.append(OCRResult(
                            text=f"[Text detected - install Tesseract to read]",
                            confidence=0.5,
                            bounding_box=bbox
                        ))

            if ocr_results:
                logger.debug(f"Fallback detected {len(ocr_results)} potential text regions")

            return ocr_results[:10]  # Limit to top 10 regions

        except Exception as e:
            logger.warning(f"Fallback text detection failed: {e}")
            return []

    def extract_text_from_array(
        self,
        image_array: np.ndarray,
        detail: int = 1
    ) -> List[OCRResult]:
        """Extract text from numpy array"""
        try:
            # Save to temp file and process
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, image_array)
                return self.extract_text(tmp.name)
        except Exception as e:
            logger.warning(f"OCR from array failed: {e}")
            return []

    def get_full_text(
        self,
        image_path: str,
        min_confidence: float = 0.0
    ) -> str:
        """Get all text from image as a single string"""
        results = self.extract_text(image_path)

        texts = [
            result.text
            for result in results
            if result.confidence >= min_confidence and not result.text.startswith('[Text detected')
        ]

        return " ".join(texts)

    def extract_text_with_visualization(
        self,
        image_path: str,
        output_path: str = None
    ) -> Tuple[List[OCRResult], str]:
        """Extract text and create visualization"""
        results = self.extract_text(image_path)

        image = cv2.imread(image_path)

        for result in results:
            bbox = result.bounding_box
            if bbox:
                points = [(int(point[0]), int(point[1])) for point in bbox]

                cv2.polylines(
                    image,
                    [np.array(points)],
                    isClosed=True,
                    color=(0, 255, 0),
                    thickness=2
                )

                cv2.putText(
                    image,
                    f"{result.confidence:.2f}",
                    (points[0][0], points[0][1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1
                )

        if output_path is None:
            output_path = image_path.replace(".jpg", "_ocr.jpg").replace(".png", "_ocr.png")

        cv2.imwrite(output_path, image)
        logger.info(f"Visualization saved to: {output_path}")

        return results, output_path

    def detect_sensitive_info(
        self,
        image_path: str,
        patterns: dict = None
    ) -> List[dict]:
        """Detect potentially sensitive information in text"""

        # Default sensitive patterns
        default_patterns = {
            "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
            "credit_card": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            "phone": r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
            "phone_intl": r'\b\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b',
            "ip_address": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'
        }

        if patterns:
            default_patterns.update(patterns)

        full_text = self.get_full_text(image_path)

        detected = []
        for pattern_name, pattern in default_patterns.items():
            matches = re.findall(pattern, full_text)
            if matches:
                detected.append({
                    "type": pattern_name,
                    "matches": matches,
                    "count": len(matches),
                    "text": full_text
                })

        if detected:
            logger.warning(f"Detected {len(detected)} types of sensitive information")

        return detected

    def get_reader_info(self) -> dict:
        """Get information about the OCR reader"""
        return {
            "engine": "Tesseract" if self.ocr_available else "Fallback",
            "status": "Ready" if self.ocr_available else "Limited (install Tesseract for full OCR)",
            "languages": self.languages
        }

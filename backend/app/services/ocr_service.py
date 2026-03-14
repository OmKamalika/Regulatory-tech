"""
OCR service with EasyOCR as primary engine.

Priority:
1. EasyOCR  — no binary install needed, reads actual text
2. Tesseract — if pytesseract + binary installed
3. OpenCV fallback — detects regions only, cannot read text
"""
import logging
import os
import sys
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
    OCR service with EasyOCR as primary engine.
    Falls back to Tesseract, then OpenCV region detection.
    """

    def __init__(self, languages: List[str] = None, use_gpu: bool = False):
        self.languages = languages or ['en']
        self.use_gpu = use_gpu
        self.engine = "fallback"

        # Priority 1: EasyOCR (no binary install needed)
        try:
            import easyocr
            self.reader = easyocr.Reader(self.languages, gpu=self.use_gpu, verbose=False)
            self.engine = "easyocr"
            logger.info("OCR engine: EasyOCR")
            return
        except Exception as e:
            logger.warning(f"EasyOCR not available: {e}")

        # Priority 2: Tesseract
        try:
            import pytesseract
            tesseract_cmd = os.environ.get("TESSERACT_CMD")
            if not tesseract_cmd:
                if sys.platform == "win32":
                    tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
                else:
                    tesseract_cmd = "tesseract"
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            pytesseract.get_tesseract_version()
            self.pytesseract = pytesseract
            self.engine = "tesseract"
            logger.info("OCR engine: Tesseract")
            return
        except Exception as e:
            logger.warning(f"Tesseract not available: {e}")

        # Priority 3: OpenCV fallback (regions only, no text reading)
        logger.warning("OCR engine: OpenCV fallback (cannot read text — PII detection will not work)")

    def extract_text(self, image_path: str, **kwargs) -> List[OCRResult]:
        """Extract text from image using the best available engine."""
        logger.debug(f"Extracting text from: {image_path}")

        if self.engine == "easyocr":
            return self._extract_with_easyocr(image_path)
        elif self.engine == "tesseract":
            return self._extract_with_tesseract(image_path)
        else:
            return self._extract_with_fallback(image_path)

    def _extract_with_easyocr(self, image_path: str) -> List[OCRResult]:
        """Extract text using EasyOCR."""
        try:
            results = self.reader.readtext(image_path)
            ocr_results = []
            for (bbox, text, confidence) in results:
                if not text or not text.strip() or confidence < 0.3:
                    continue
                # EasyOCR bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                ocr_results.append(OCRResult(
                    text=text.strip(),
                    confidence=round(confidence, 3),
                    bounding_box=[[int(p[0]), int(p[1])] for p in bbox],
                ))
            logger.debug(f"EasyOCR extracted {len(ocr_results)} text regions")
            return ocr_results
        except Exception as e:
            logger.warning(f"EasyOCR failed: {e}")
            return self._extract_with_fallback(image_path)

    def _extract_with_tesseract(self, image_path: str) -> List[OCRResult]:
        """Extract text using Tesseract OCR."""
        try:
            from PIL import Image
            image = Image.open(image_path)
            data = self.pytesseract.image_to_data(
                image, output_type=self.pytesseract.Output.DICT
            )
            ocr_results = []
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                conf = float(data['conf'][i])
                if not text or conf < 0:
                    continue
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                ocr_results.append(OCRResult(
                    text=text,
                    confidence=conf / 100.0,
                    bounding_box=[[x, y], [x+w, y], [x+w, y+h], [x, y+h]],
                ))
            logger.debug(f"Tesseract extracted {len(ocr_results)} text regions")
            return ocr_results
        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")
            return self._extract_with_fallback(image_path)

    def _extract_with_fallback(self, image_path: str) -> List[OCRResult]:
        """
        OpenCV region detection fallback.
        Detects WHERE text is but cannot read it — PII detection will not work.
        """
        try:
            image = cv2.imread(image_path)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            ocr_results = []
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                if w > 20 and h > 10 and w < image.shape[1] * 0.8 and h < image.shape[0] * 0.8:
                    roi = gray[y:y+h, x:x+w]
                    if np.std(roi) > 20:
                        ocr_results.append(OCRResult(
                            text="",  # Cannot read text without a proper OCR engine
                            confidence=0.0,
                            bounding_box=[[x, y], [x+w, y], [x+w, y+h], [x, y+h]],
                        ))
            return ocr_results[:10]
        except Exception as e:
            logger.warning(f"Fallback text detection failed: {e}")
            return []

    def extract_text_from_array(self, image_array: np.ndarray, **kwargs) -> List[OCRResult]:
        """Extract text from numpy array."""
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, image_array)
                return self.extract_text(tmp.name)
        except Exception as e:
            logger.warning(f"OCR from array failed: {e}")
            return []

    def get_full_text(self, image_path: str, min_confidence: float = 0.0) -> str:
        """Get all text from image as a single string."""
        results = self.extract_text(image_path)
        texts = [r.text for r in results if r.text and r.confidence >= min_confidence]
        return " ".join(texts)

    def extract_text_with_visualization(
        self, image_path: str, output_path: str = None
    ) -> Tuple[List[OCRResult], str]:
        """Extract text and create visualization."""
        results = self.extract_text(image_path)
        image = cv2.imread(image_path)
        for result in results:
            if result.bounding_box:
                points = [(int(p[0]), int(p[1])) for p in result.bounding_box]
                cv2.polylines(image, [np.array(points)], isClosed=True, color=(0, 255, 0), thickness=2)
                cv2.putText(image, f"{result.confidence:.2f}", (points[0][0], points[0][1] - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        if output_path is None:
            output_path = image_path.replace(".jpg", "_ocr.jpg").replace(".png", "_ocr.png")
        cv2.imwrite(output_path, image)
        return results, output_path

    def detect_sensitive_info(self, image_path: str, patterns: dict = None) -> List[dict]:
        """Detect potentially sensitive information in extracted text."""
        default_patterns = {
            "phone_india": r'\+?91[.\-\s]?[6-9]\d{9}',
            "phone_10": r'\b[6-9]\d{9}\b',
            "email": r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
            "credit_card": r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            "aadhaar": r'\b\d{4}[\-\s]\d{4}[\-\s]\d{4}\b',
            "pan": r'\b[A-Z]{5}\d{4}[A-Z]\b',
            "gst": r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b',
            "ip_address": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        }
        if patterns:
            default_patterns.update(patterns)
        full_text = self.get_full_text(image_path)
        detected = []
        for pattern_name, pattern in default_patterns.items():
            matches = re.findall(pattern, full_text)
            if matches:
                detected.append({"type": pattern_name, "matches": matches, "count": len(matches)})
        if detected:
            logger.warning(f"Detected {len(detected)} types of sensitive information")
        return detected

    def get_reader_info(self) -> dict:
        """Get information about the OCR engine in use."""
        return {
            "engine": self.engine,
            "languages": self.languages,
            "can_read_text": self.engine in ("easyocr", "tesseract"),
        }

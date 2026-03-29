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

from app.config import settings
from app.services.frame_preprocessor import FramePreprocessor

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Data class for OCR result"""
    text: str
    confidence: float
    bounding_box: List[List[int]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]


class OCRService:
    """
    OCR service with Qwen2-VL as primary engine (via Ollama).
    Falls back to EasyOCR, then Tesseract, then OpenCV region detection.
    """

    def __init__(self, languages: List[str] = None, use_gpu: bool = False):
        self.languages = languages or ['en']
        self.use_gpu = use_gpu
        self.engine = "fallback"
        self.preprocessor = FramePreprocessor()

        # Priority 1: Qwen2-VL via Ollama (best accuracy on video frames)
        if self._init_qwen():
            self.engine = "qwen"
            logger.info("OCR engine: %s (Ollama)", getattr(self, '_qwen_model', 'vision'))
            return

        # Priority 2: EasyOCR (no binary install needed) — model loads lazily on first use
        try:
            import easyocr as _easyocr_lib  # check it's installed without loading models
            self._easyocr_lib = _easyocr_lib
            self.reader = None  # populated on first OCR call via _get_reader()
            self.engine = "easyocr"
            self._apply_easyocr_patch()
            logger.info("OCR engine: EasyOCR (model loads on first use)")
            return
        except ImportError as e:
            logger.warning(f"EasyOCR not available: {e}")

        # Priority 3: Tesseract
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

    def _init_qwen(self) -> bool:
        """Probe Ollama: return True if the configured qwen vision model is available."""
        model = settings.OLLAMA_OCR_MODEL
        if not model:
            return False
        try:
            import requests as _req
            resp = _req.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=3)
            if resp.status_code != 200:
                return False
            available = [m["name"] for m in resp.json().get("models", [])]
            model_base = model.split(":")[0]
            if not any(model_base in m for m in available):
                logger.warning(
                    "Qwen2-VL not found in Ollama (falling back to EasyOCR). "
                    "Pull it with: docker exec -it regtech_ollama ollama pull %s", model,
                )
                return False
            self._qwen_model = model
            self._qwen_base_url = settings.OLLAMA_BASE_URL
            return True
        except Exception as e:
            logger.debug("Qwen2-VL probe failed (Ollama not running?): %s", e)
            return False

    def _extract_with_qwen(self, image_path: str) -> List[OCRResult]:
        """Extract text using Qwen2-VL via Ollama /api/chat."""
        import base64
        import requests as _req
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            payload = {
                "model": self._qwen_model,
                "messages": [{
                    "role": "user",
                    "content": (
                        "Extract all text visible in this image. "
                        "Return only the raw text lines, one per line. "
                        "If no text is visible, return an empty response."
                    ),
                    "images": [img_b64],
                }],
                "stream": False,
            }
            resp = _req.post(
                f"{self._qwen_base_url}/api/chat",
                json=payload,
                timeout=300,  # 5 min — LLaVA/Qwen2-VL 7B on CPU can take 2-3 min per frame
            )
            resp.raise_for_status()
            text = resp.json()["message"]["content"].strip()
            if not text:
                return []
            results = [
                OCRResult(text=line.strip(), confidence=1.0, bounding_box=[])
                for line in text.splitlines()
                if line.strip()
            ]
            logger.debug("Vision OCR extracted %d text lines from %s", len(results), image_path)
            return results
        except Exception as e:
            import traceback
            logger.warning(
                "Vision OCR failed on %s: %s\n%s",
                image_path, e, traceback.format_exc(),
            )
            # Do not fall back to EasyOCR — self.reader is not initialised when engine=qwen
            return []

    def _apply_easyocr_patch(self) -> None:
        """Patch EasyOCR 1.7.x internal bugs that cause 'too many values to unpack'.

        Two separate bugs:
        1. detection.py test_net() may return >2 values; get_textbox() expects 2.
        2. utils.py get_image_list() does `maximum_y, maximum_x = img.shape` which
           fails when img is a 3-channel (color) array — expects 2D grayscale.
           Triggered when the frame preprocessor returns a color image.
        """
        # Patch 1: test_net return-value normalisation
        try:
            import easyocr.detection as _det
            _orig_test_net = _det.test_net

            def _safe_test_net(*args, **kwargs):
                result = _orig_test_net(*args, **kwargs)
                if isinstance(result, tuple) and len(result) != 2:
                    return result[0], result[1]
                return result

            _det.test_net = _safe_test_net
            logger.info("Applied EasyOCR patch 1: test_net return-value fix")
        except Exception as e:
            logger.warning("EasyOCR patch 1 failed (non-fatal): %s", e)

        # Patch 2: get_image_list 3-channel image fix (utils.py line 582)
        # easyocr.py does `from .utils import get_image_list` at import time, so
        # patching easyocr.utils has no effect — must patch the bound reference
        # inside the easyocr module directly.
        try:
            import easyocr.utils as _utils
            import easyocr.easyocr as _easyocr_mod
            _orig_get_image_list = _utils.get_image_list

            def _safe_get_image_list(h_list, f_list, img, model_height=64, sort_output=True):
                if hasattr(img, "ndim") and img.ndim == 3:
                    channels = img.shape[2]
                    if channels == 3:
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    elif channels == 4:
                        img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
                    elif channels == 1:
                        img = img[:, :, 0]  # (H,W,1) → (H,W)
                return _orig_get_image_list(h_list, f_list, img,
                                            model_height=model_height,
                                            sort_output=sort_output)

            # Patch both the utils module AND the bound reference inside easyocr.py
            _utils.get_image_list = _safe_get_image_list
            _easyocr_mod.get_image_list = _safe_get_image_list
            logger.info("Applied EasyOCR patch 2: get_image_list 3-channel fix")
        except Exception as e:
            logger.warning("EasyOCR patch 2 failed (non-fatal): %s", e)

        # Patch 3: PIL.Image.ANTIALIAS removed in Pillow 10 — replaced by LANCZOS
        # easyocr/utils.py compute_ratio_and_resize uses Image.ANTIALIAS directly.
        try:
            from PIL import Image as _PILImage
            if not hasattr(_PILImage, "ANTIALIAS"):
                _PILImage.ANTIALIAS = _PILImage.LANCZOS
                logger.info("Applied EasyOCR patch 3: PIL.Image.ANTIALIAS → LANCZOS")
        except Exception as e:
            logger.warning("EasyOCR patch 3 failed (non-fatal): %s", e)

    def extract_text(self, image_path: str, **kwargs) -> List[OCRResult]:
        """Extract text from image using the best available engine."""
        logger.debug(f"Extracting text from: {image_path}")

        # ── Frame preprocessing gate ─────────────────────────────────────────
        # Runs before OCR to improve contrast, remove noise, and skip unreadable
        # frames (too blurry or too dark). Does NOT affect YOLO — visual_analyzer
        # reads the original file path directly.
        if settings.ENABLE_FRAME_PREPROCESSING:
            preprocessed_array, meta = self.preprocessor.preprocess(image_path)
            if meta.get("skipped"):
                # Frame is unreadable — no OCR result is better than a wrong one
                logger.info(
                    "OCR skipped frame [reason=%s, blur=%.1f, brightness=%.1f]: %s",
                    meta.get("reason"), meta.get("blur_score", 0.0),
                    meta.get("brightness", 0.0), image_path,
                )
                return []
            elif preprocessed_array is not None:
                # Enhanced image available — pass array to OCR (avoids re-compression)
                return self.extract_text_from_array(preprocessed_array)
            # preprocessed_array is None + not skipped = preprocessing error:
            # fall through to original path so OCR still runs on the raw frame

        if self.engine == "qwen":
            return self._extract_with_qwen(image_path)
        elif self.engine == "easyocr":
            return self._extract_with_easyocr(image_path)
        elif self.engine == "tesseract":
            return self._extract_with_tesseract(image_path)
        else:
            return self._extract_with_fallback(image_path)

    def _get_reader(self):
        """Return EasyOCR reader, initializing model on first call."""
        if self.reader is None:
            logger.info("Loading EasyOCR model (first use — takes ~60s on CPU)...")
            self.reader = self._easyocr_lib.Reader(
                self.languages, gpu=self.use_gpu, verbose=False
            )
            logger.info("EasyOCR model loaded.")
        return self.reader

    def _extract_with_easyocr(self, image_path: str) -> List[OCRResult]:
        """Extract text using EasyOCR."""
        try:
            results = self._get_reader().readtext(image_path)
            ocr_results = []
            rejected = []
            for result in results:
                # Handle both (bbox, text, confidence) and (bbox, text) formats
                # across EasyOCR versions
                try:
                    if len(result) == 3:
                        bbox, text, confidence = result
                    elif len(result) == 2:
                        bbox, text = result
                        confidence = 1.0
                    else:
                        continue
                except (ValueError, TypeError):
                    continue
                if not text or not text.strip():
                    continue
                if confidence < 0.1:
                    # Log what was discarded so PII misses are visible in logs
                    rejected.append(f"{text.strip()!r} (conf={confidence:.2f})")
                    continue
                # EasyOCR bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                ocr_results.append(OCRResult(
                    text=text.strip(),
                    confidence=round(confidence, 3),
                    bounding_box=[[int(p[0]), int(p[1])] for p in bbox],
                ))
            if rejected:
                logger.debug(
                    "EasyOCR discarded %d low-confidence regions: %s",
                    len(rejected), ", ".join(rejected[:10]),
                )
            logger.debug("EasyOCR extracted %d text regions", len(ocr_results))
            return ocr_results
        except Exception as e:
            import traceback
            logger.warning(
                "EasyOCR failed on %s: %s\n%s",
                image_path, e, traceback.format_exc(),
            )
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
        """Extract text from numpy array.

        Calls the engine directly (bypasses preprocessing) to avoid infinite
        recursion when extract_text() delegates here after preprocessing.
        Converts to grayscale before writing so EasyOCR's internal 2D-shape
        assumptions are never violated regardless of preprocessor output format.
        """
        try:
            import tempfile
            # Normalise: EasyOCR internals require 2D grayscale input
            if image_array.ndim == 3:
                image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, image_array)
                if self.engine == "qwen":
                    return self._extract_with_qwen(tmp.name)
                elif self.engine == "easyocr":
                    return self._extract_with_easyocr(tmp.name)
                elif self.engine == "tesseract":
                    return self._extract_with_tesseract(tmp.name)
                else:
                    return self._extract_with_fallback(tmp.name)
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
        from app.common.patterns import PII_PATTERNS, GST_PATTERN
        combined = dict(PII_PATTERNS)
        combined["gst"] = GST_PATTERN.pattern
        if patterns:
            combined.update(patterns)
        full_text = self.get_full_text(image_path)
        detected = []
        for pattern_name, pattern in combined.items():
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
            "can_read_text": self.engine in ("qwen", "easyocr", "tesseract"),
            "model_loaded": self.engine != "easyocr" or self.reader is not None,
        }

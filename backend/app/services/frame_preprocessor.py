"""
Frame Preprocessor — improves frame quality before OCR.

Applied automatically before every OCR call when ENABLE_FRAME_PREPROCESSING=True.
YOLO (visual analysis) always receives raw frames — no change there.

Steps, in order:
  1. Blur gate      — skip frames too blurry to read (Laplacian variance)
  2. Brightness gate — skip frames too dark or overexposed
  3. Bilateral filter — remove noise without blurring text edges
  4. CLAHE on L     — fix uneven lighting (bright window, dark subject)
  5. Sharpen        — sharpen thin digit strokes (Aadhaar, PAN, phone numbers)
"""
import logging
import numpy as np
import cv2
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class FramePreprocessor:
    """
    Preprocesses video frames before OCR to improve text detection accuracy.

    Usage:
        preprocessor = FramePreprocessor()
        array, meta = preprocessor.preprocess("/path/to/frame.jpg")
        if meta["skipped"]:
            pass  # frame is unreadable, skip OCR
        elif array is not None:
            # use array (numpy BGR) instead of original file
    """

    def __init__(self):
        # CLAHE instance is reused across frames (avoids re-allocating each call)
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

        # Unsharp mask kernel — sharpens text edges
        self._sharpen_kernel = np.array(
            [[0, -1, 0],
             [-1, 5, -1],
             [0, -1, 0]],
            dtype=np.float32,
        )
        logger.debug("FramePreprocessor initialised")

    def preprocess(
        self,
        image_path: str,
        blur_threshold: float = None,
        min_brightness: int = None,
        max_brightness: int = None,
    ) -> Tuple[Optional[np.ndarray], dict]:
        """
        Preprocess a frame for OCR.

        Args:
            image_path:      Path to the JPEG frame on disk.
            blur_threshold:  Override config PREPROCESS_BLUR_THRESHOLD.
            min_brightness:  Override config PREPROCESS_MIN_BRIGHTNESS.
            max_brightness:  Override config PREPROCESS_MAX_BRIGHTNESS.

        Returns:
            (array, meta) where:
              - array is None  → frame skipped; do not run OCR
              - array is ndarray → enhanced BGR image; pass to OCR instead of original
              - meta dict has keys: skipped, reason, blur_score, brightness, steps_applied
        """
        # Resolve thresholds (allow per-call override for testing)
        from app.config import settings
        _blur_thresh  = blur_threshold  if blur_threshold  is not None else settings.PREPROCESS_BLUR_THRESHOLD
        _min_bright   = min_brightness  if min_brightness  is not None else settings.PREPROCESS_MIN_BRIGHTNESS
        _max_bright   = max_brightness  if max_brightness  is not None else settings.PREPROCESS_MAX_BRIGHTNESS

        meta = {
            "skipped": False,
            "reason": "ok",
            "blur_score": 0.0,
            "brightness": 0.0,
            "steps_applied": [],
        }

        try:
            # ── Load ───────────────────────────────────────────────────────
            image = cv2.imread(image_path)
            if image is None:
                logger.warning("FramePreprocessor: could not read image: %s", image_path)
                meta.update({"skipped": True, "reason": "unreadable_file"})
                return None, meta

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            # ── Step 1: Blur gate ─────────────────────────────────────────
            blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            meta["blur_score"] = round(blur_score, 2)

            if blur_score < _blur_thresh:
                logger.info(
                    "FramePreprocessor: skipping frame (blur=%.1f < threshold=%.1f): %s",
                    blur_score, _blur_thresh, image_path,
                )
                meta.update({"skipped": True, "reason": "blur"})
                return None, meta

            # ── Step 2: Brightness gate ───────────────────────────────────
            brightness = float(np.mean(gray))
            meta["brightness"] = round(brightness, 2)

            if brightness < _min_bright:
                logger.info(
                    "FramePreprocessor: skipping frame (brightness=%.1f < min=%d): %s",
                    brightness, _min_bright, image_path,
                )
                meta.update({"skipped": True, "reason": "too_dark"})
                return None, meta

            if brightness > _max_bright:
                logger.info(
                    "FramePreprocessor: skipping frame (brightness=%.1f > max=%d): %s",
                    brightness, _max_bright, image_path,
                )
                meta.update({"skipped": True, "reason": "overexposed"})
                return None, meta

            # ── Step 3: Bilateral filter (denoise without edge blur) ───────
            denoised = cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)
            meta["steps_applied"].append("bilateral_filter")

            # ── Step 4: CLAHE on luminance channel (fix uneven lighting) ──
            lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
            l_channel, a_channel, b_channel = cv2.split(lab)
            l_enhanced = self._clahe.apply(l_channel)
            lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
            enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
            meta["steps_applied"].append("clahe")

            # ── Step 5: Sharpen text edges ─────────────────────────────────
            sharpened = cv2.filter2D(enhanced, -1, self._sharpen_kernel)
            meta["steps_applied"].append("sharpen")

            logger.debug(
                "FramePreprocessor: processed [blur=%.1f, brightness=%.1f, steps=%s]: %s",
                blur_score, brightness, ",".join(meta["steps_applied"]), image_path,
            )
            return sharpened, meta

        except Exception as e:
            logger.warning(
                "FramePreprocessor: preprocessing failed for %s: %s — falling back to original",
                image_path, e,
            )
            meta.update({"skipped": False, "reason": "preprocessing_error"})
            return None, meta

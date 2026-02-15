"""
Visual analysis service using YOLO v8 for object detection.
"""
from ultralytics import YOLO
import logging
from typing import List, Dict
from dataclasses import dataclass
import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DetectedObject:
    """Data class for detected object"""
    class_name: str
    confidence: float
    bounding_box: List[float]  # [x1, y1, x2, y2]
    class_id: int


class VisualAnalyzer:
    """
    Visual analysis service using YOLO v8 for object and person detection.
    Useful for detecting UI elements, people, data displays, etc.
    """

    def __init__(self, model_path: str = None):
        self.model_path = model_path or settings.YOLO_MODEL

        logger.info(f"Loading YOLO model: {self.model_path}")

        try:
            self.model = YOLO(self.model_path)
            logger.info(f"YOLO model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            raise

    def analyze_image(
        self,
        image_path: str,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45
    ) -> List[DetectedObject]:
        """
        Analyze image and detect objects.

        Args:
            image_path: Path to image file
            conf_threshold: Confidence threshold for detections
            iou_threshold: IoU threshold for NMS

        Returns:
            List of DetectedObject instances
        """
        logger.debug(f"Analyzing image: {image_path}")

        try:
            # Run inference
            results = self.model(
                image_path,
                conf=conf_threshold,
                iou=iou_threshold,
                verbose=False
            )

            # Parse results
            detected_objects = []

            for result in results:
                boxes = result.boxes

                for box in boxes:
                    # Get box coordinates and metadata
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = result.names[cls_id]

                    detected_objects.append(DetectedObject(
                        class_name=cls_name,
                        confidence=conf,
                        bounding_box=[x1, y1, x2, y2],
                        class_id=cls_id
                    ))

            logger.debug(f"Detected {len(detected_objects)} objects")
            return detected_objects

        except Exception as e:
            logger.error(f"Error analyzing image: {e}")
            raise

    def detect_persons(self, image_path: str) -> List[DetectedObject]:
        """
        Detect persons in image.

        Args:
            image_path: Path to image file

        Returns:
            List of detected persons
        """
        all_objects = self.analyze_image(image_path)

        # Filter for person class (class_id = 0 in COCO dataset)
        persons = [obj for obj in all_objects if obj.class_name == "person"]

        logger.info(f"Detected {len(persons)} person(s)")
        return persons

    def get_summary(self, image_path: str) -> Dict:
        """
        Get analysis summary with object counts.

        Args:
            image_path: Path to image file

        Returns:
            Dictionary with analysis summary
        """
        objects = self.analyze_image(image_path)

        # Count objects by class
        class_counts = {}
        for obj in objects:
            class_counts[obj.class_name] = class_counts.get(obj.class_name, 0) + 1

        # Get person and face count
        person_count = class_counts.get("person", 0)

        summary = {
            "total_objects": len(objects),
            "unique_classes": len(class_counts),
            "class_counts": class_counts,
            "persons_detected": person_count,
            "has_persons": person_count > 0
        }

        return summary

    def annotate_image(
        self,
        image_path: str,
        output_path: str = None,
        conf_threshold: float = 0.25
    ) -> str:
        """
        Create annotated image with bounding boxes.

        Args:
            image_path: Path to input image
            output_path: Path to save annotated image (optional)
            conf_threshold: Confidence threshold

        Returns:
            Path to annotated image
        """
        # Run detection
        results = self.model(
            image_path,
            conf=conf_threshold,
            verbose=False
        )

        # Get annotated image
        annotated_frame = results[0].plot()

        # Save output
        if output_path is None:
            output_path = image_path.replace(".jpg", "_annotated.jpg").replace(".png", "_annotated.png")

        cv2.imwrite(output_path, annotated_frame)
        logger.info(f"Annotated image saved to: {output_path}")

        return output_path

    def batch_analyze(
        self,
        image_paths: List[str],
        conf_threshold: float = 0.25
    ) -> List[Dict]:
        """
        Analyze multiple images in batch.

        Args:
            image_paths: List of image paths
            conf_threshold: Confidence threshold

        Returns:
            List of analysis summaries
        """
        logger.info(f"Batch analyzing {len(image_paths)} images")

        results = []
        for image_path in image_paths:
            try:
                summary = self.get_summary(image_path)
                summary["image_path"] = image_path
                summary["success"] = True
                results.append(summary)
            except Exception as e:
                logger.error(f"Error analyzing {image_path}: {e}")
                results.append({
                    "image_path": image_path,
                    "success": False,
                    "error": str(e)
                })

        return results

    def detect_pii_indicators(self, image_path: str) -> Dict:
        """
        Detect visual indicators of PII (Personally Identifiable Information).
        Looks for monitors, screens, laptops, phones where PII might be displayed.

        Args:
            image_path: Path to image file

        Returns:
            Dictionary with PII indicator analysis
        """
        objects = self.analyze_image(image_path)

        # Classes that might display PII
        pii_display_classes = {
            "laptop", "cell phone", "monitor", "tv", "keyboard",
            "mouse", "remote", "book"
        }

        detected_displays = [
            obj for obj in objects
            if obj.class_name.lower() in pii_display_classes
        ]

        has_persons = any(obj.class_name == "person" for obj in objects)

        analysis = {
            "has_display_devices": len(detected_displays) > 0,
            "display_devices": [
                {
                    "type": obj.class_name,
                    "confidence": obj.confidence,
                    "bounding_box": obj.bounding_box
                }
                for obj in detected_displays
            ],
            "has_persons": has_persons,
            "risk_level": "high" if detected_displays and has_persons else "medium" if detected_displays else "low"
        }

        return analysis

    def get_model_info(self) -> Dict:
        """Get information about the loaded YOLO model"""
        return {
            "model_path": self.model_path,
            "model_type": self.model.type,
            "task": self.model.task,
            "device": str(self.model.device),
            "names": self.model.names
        }

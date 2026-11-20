import logging
from functools import lru_cache

import cv2                                    # type: ignore
import numpy as np                            # type: ignore
from ultralytics import YOLO                  # type: ignore

logger = logging.getLogger(__name__)

MODEL_NAME = "yolov8n.pt"

# COCO class IDs:
# 2 = car
# 3 = motorcycle
# 5 = bus
# 7 = truck

VEHICLE_CLASSES = [2, 3, 5, 7]


@lru_cache(maxsize=1)
def get_model():
    """
    Load the YOLO model once and reuse it.
    """
    logger.info("Loading YOLO model: %s", MODEL_NAME)
    return YOLO(MODEL_NAME)


def detect_vehicles(image_bytes: bytes) -> dict:
    """
    Detect vehicles in an image.

    Returns vehicle classes, confidence scores
    and bounding box coordinates.
    """

    image_array = np.frombuffer(
        image_bytes,
        dtype=np.uint8,
    )

    image = cv2.imdecode(
        image_array,
        cv2.IMREAD_COLOR,
    )

    if image is None:
        raise ValueError("Unable to decode image.")

    height, width = image.shape[:2]

    model = get_model()

    results = model.predict(
        source=image,
        conf=0.40,
        classes=VEHICLE_CLASSES,
        verbose=False,
    )

    detections = []

    for result in results:
        for box in result.boxes:
            class_id = int(box.cls.item())

            class_name = model.names[class_id]

            confidence = float(box.conf.item())

            x1, y1, x2, y2 = (
                box.xyxy[0].tolist()
            )

            detections.append({
                "vehicle_type": class_name,
                "class_id": class_id,
                "confidence": round(confidence, 4),
                "bounding_box": {
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                },
            })

    return {
        "model": MODEL_NAME,
        "image_width": width,
        "image_height": height,
        "vehicle_count": len(detections),
        "detections": detections,
    }

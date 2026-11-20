import logging
from functools import lru_cache
from pathlib import Path

import cv2                             # type: ignore
import numpy as np                     # type: ignore
from ultralytics import YOLO           # type: ignore

logger = logging.getLogger(__name__)

MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "license_plate_detector.pt"
)

CONFIDENCE_THRESHOLD = 0.25
IMAGE_SIZE = 1280


@lru_cache(maxsize=1)
def get_plate_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"License plate model not found: {MODEL_PATH}"
        )

    logger.info("Loading license plate model: %s", MODEL_PATH)

    return YOLO(str(MODEL_PATH))


def detect_number_plates(image_bytes: bytes) -> dict:
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)

    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Unable to decode evidence image.")

    height, width = image.shape[:2]

    model = get_plate_model()

    results = model.predict(
        source=image,
        conf=CONFIDENCE_THRESHOLD,
        imgsz=IMAGE_SIZE,
        verbose=False,
    )

    detections = []

    for result in results:
        for box in result.boxes:
            class_id = int(box.cls.item())
            confidence = float(box.conf.item())

            x1, y1, x2, y2 = box.xyxy[0].tolist()

            detections.append({
                "class_id": class_id,
                "class_name": model.names[class_id],
                "confidence": round(confidence, 4),
                "bounding_box": {
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                },
            })

    return {
        "model": MODEL_PATH.name,
        "image_width": width,
        "image_height": height,
        "plate_count": len(detections),
        "detections": detections,
    }

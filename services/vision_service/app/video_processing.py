import logging
import os
import tempfile
import cv2                                       # type: ignore

from collections import defaultdict
from pathlib import Path
from uuid import UUID
from typing import Literal

from .kafka_publisher import publish_recognition_event

from fastapi import APIRouter, HTTPException     # type: ignore
from minio.error import S3Error                  # type: ignore
from pydantic import BaseModel, Field            # type: ignore

from .config import MINIO_BUCKET
from .storage import minio_client
from .detector import detect_vehicles
from .plate_detector import detect_number_plates
from .ocr import extract_plate_text
from .consensus import build_plate_consensus
from .publication_policy import evaluate_publication_eligibility

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/processing",
    tags=["Video Processing"],
)


class VideoProcessingRequest(BaseModel):
    video_id: UUID
    estate_id: UUID
    gate_id: UUID

    object_key: str = Field(
        min_length=1,
        max_length=1024,
    )

    direction: Literal["ENTRY", "EXIT"]

    sample_interval_seconds: float = Field(
        default=1.0,
        ge=0.2,
        le=10.0,
    )

    max_frames: int = Field(
        default=120,
        ge=1,
        le=300,
    )


def validate_video_key(request):
    expected_prefix = (
        f"videos/{request.estate_id}/gates/{request.gate_id}/"
    )

    if not request.object_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=400,
            detail="Video object key does not match the supplied estate and gate.",
        )

    filename = request.object_key.rsplit("/", 1)[-1]

    allowed_filenames = {
        f"{request.video_id}.mp4",
        f"{request.video_id}.avi",
        f"{request.video_id}.mov",
    }

    if filename not in allowed_filenames:
        raise HTTPException(
            status_code=400,
            detail="Video ID does not match the object key.",
        )


def download_video_from_minio(object_key):
    response = None

    try:
        response = minio_client.get_object(
            MINIO_BUCKET,
            object_key,
        )

        return response.read()

    except S3Error as exc:
        logger.exception("MinIO video retrieval failed.")

        if exc.code in ("NoSuchKey", "NoSuchObject"):
            raise HTTPException(
                status_code=404,
                detail="Video was not found in MinIO.",
            )

        raise HTTPException(
            status_code=503,
            detail="Video storage is temporarily unavailable.",
        )

    except Exception:
        logger.exception("Unexpected error retrieving video.")

        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve video.",
        )

    finally:
        if response is not None:
            response.close()
            response.release_conn()



@router.post("/videos")
def process_cctv_video(request: VideoProcessingRequest):

    validate_video_key(request)

    video_bytes = download_video_from_minio(
        request.object_key
    )

    if not video_bytes:
        raise HTTPException(
            status_code=400,
            detail="Stored video is empty.",
        )

    extension = Path(request.object_key).suffix.lower()

    temporary_path = None
    capture = None

    frame_results = []

    total_vehicle_detections = 0
    total_plate_detections = 0

    try:
        with tempfile.NamedTemporaryFile(
            suffix=extension,
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            temporary_file.write(video_bytes)

        capture = cv2.VideoCapture(temporary_path)

        if not capture.isOpened():
            raise HTTPException(
                status_code=400,
                detail="OpenCV could not open the stored video.",
            )

        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = int(
            capture.get(cv2.CAP_PROP_FRAME_COUNT)
        )

        if fps <= 0 or frame_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="Unable to read video frame rate or frame count.",
            )

        duration_seconds = frame_count / fps

        sample_every_n_frames = max(
            1,
            round(fps * request.sample_interval_seconds),
        )

        frame_index = 0

        while len(frame_results) < request.max_frames:
            success, frame = capture.read()

            if not success:
                break

            if frame_index % sample_every_n_frames == 0:

                timestamp_seconds = round(
                    frame_index / fps,
                    3,
                )

                encode_success, encoded_image = cv2.imencode(
                    ".jpg",
                    frame,
                )

                if not encode_success:
                    logger.warning(
                        "Could not encode frame %s.",
                        frame_index,
                    )
                    frame_index += 1
                    continue

                frame_bytes = encoded_image.tobytes()

                # Stage 1: Detect vehicles.
                vehicle_result = detect_vehicles(frame_bytes)

                total_vehicle_detections += (
                    vehicle_result["vehicle_count"]
                )

                # Stage 2: Detect number plates.
                plate_result = detect_number_plates(frame_bytes)

                total_plate_detections += (
                    plate_result["plate_count"]
                )

                # Stage 3: Recognize plate characters.
                recognition_result = extract_plate_text(
                    frame_bytes,
                    plate_result["detections"],
                )

                frame_results.append({
                    "frame_index": frame_index,
                    "timestamp_seconds": timestamp_seconds,
                    "image_width": plate_result["image_width"],
                    "image_height": plate_result["image_height"],
                    "vehicle_count": vehicle_result["vehicle_count"],
                    "plate_count": plate_result["plate_count"],
                    "recognized_plates": recognition_result[
                        "recognized_plates"
                    ],
                    "skipped_regions": recognition_result[
                        "skipped_regions"
                    ],
                })

            frame_index += 1

        if not frame_results:
            raise HTTPException(
                status_code=400,
                detail="No frames could be extracted from the video.",
            )

    except HTTPException:
        raise

    except Exception:
        logger.exception("CCTV video processing failed.")

        raise HTTPException(
            status_code=500,
            detail="CCTV video processing failed.",
        )

    finally:
        if capture is not None:
            capture.release()

        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)

    consolidated_plates = build_plate_consensus(
        frame_results
    )

    published_events = []
    publication_failures = []

    for plate in consolidated_plates:
        registration = plate["recognized_text"]

        eligible, reason = evaluate_publication_eligibility(plate)

        if not eligible:
            plate["publication_status"] = "HELD_FOR_REVIEW"
            plate["publication_reason"] = reason

            logger.info(
                "ANPR publication held: registration=%s reason=%s "
                "consensus_status=%s confidence=%s",
                registration,
                reason,
                plate["status"],
                plate["average_ocr_confidence"],
            )

            continue

        plate["publication_status"] = "PUBLICATION_ELIGIBLE"
        plate["publication_reason"] = reason

        try:
            event_result = publish_recognition_event(
                video_id=request.video_id,
                estate_id=request.estate_id,
                gate_id=request.gate_id,
                direction=request.direction,
                registration=registration,
                confidence=plate["average_ocr_confidence"],
                evidence_object_key=request.object_key,
                metadata={
                    "recognition_method": "MULTI_FRAME_ANPR",
                    "video_id": str(request.video_id),
                    "observation_count": plate["observation_count"],
                    "valid_observation_count": (
                        plate["valid_observation_count"]
                    ),
                    "average_ocr_confidence": (
                        plate["average_ocr_confidence"]
                    ),
                    "best_ocr_confidence": (
                        plate["best_ocr_confidence"]
                    ),
                    "character_agreement": (
                        plate["character_agreement"]
                    ),
                    "consensus_status": plate["status"],
                    "video_observations": plate["observations"],
                },
            )

            plate["publication_status"] = "HELD_FOR_REVIEW" if not eligible else "PUBLICATION_ELIGIBLE"
            plate["publication_reason"] = reason

            published_events.append(event_result)

        except Exception:
            logger.exception(
                "Kafka publication failed for registration %s",
                registration,
            )

            plate["publication_status"] = "PUBLICATION_FAILED"
            plate["publication_reason"] = "KAFKA_PUBLICATION_ERROR"

            publication_failures.append({
                "registration": registration,
                "status": "PUBLICATION_FAILED",
            })

    if publication_failures:
        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "Video recognition completed, but one or more "
                    "Kafka events could not be published."
                ),
                "publication_failures": publication_failures,
            },
        )


    return {
        "video_id": str(request.video_id),
        "estate_id": str(request.estate_id),
        "gate_id": str(request.gate_id),
        "status": "PROCESSED",
        "video_metadata": {
            "fps": round(fps, 2),
            "frame_count": frame_count,
            "duration_seconds": round(duration_seconds, 2),
        },
        "processing": {
            "sample_interval_seconds": request.sample_interval_seconds,
            "frames_processed": len(frame_results),
            "max_frames": request.max_frames,
            "vehicle_detections": total_vehicle_detections,
            "plate_detections": total_plate_detections,
        },
        "recognized_plates": consolidated_plates,
        "frame_results": frame_results,
        "kafka": {
            "events_published": len(published_events),
            "events_held_for_review": sum(
                1
                for plate in consolidated_plates
                if plate.get("publication_status") == "HELD_FOR_REVIEW"
            ),
            "events_failed": len(publication_failures),
            "events": published_events,
        },
    }

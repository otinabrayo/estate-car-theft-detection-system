import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException    # type: ignore
from minio.error import S3Error                 # type: ignore
from pydantic import BaseModel, Field           # type: ignore

from .config import MINIO_BUCKET
from .storage import minio_client
from .plate_detector import detect_number_plates

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/detection",
    tags=["Number Plate Detection"],
)


class PlateDetectionRequest(BaseModel):
    evidence_id: UUID
    estate_id: UUID
    gate_id: UUID
    object_key: str = Field(min_length=1, max_length=1024)


@router.post("/plates")
def detect_gate_number_plates(request: PlateDetectionRequest):

    expected_prefix = (
        f"evidence/{request.estate_id}/gates/{request.gate_id}/"
    )

    if not request.object_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=400,
            detail="Evidence object key does not match the supplied estate and gate.",
        )

    filename = request.object_key.rsplit("/", 1)[-1]

    allowed_filenames = {
        f"{request.evidence_id}.jpg",
        f"{request.evidence_id}.jpeg",
        f"{request.evidence_id}.png",
        f"{request.evidence_id}.webp",
    }

    if filename not in allowed_filenames:
        raise HTTPException(
            status_code=400,
            detail="Evidence ID does not match the object key.",
        )

    response = None

    try:
        response = minio_client.get_object(
            MINIO_BUCKET,
            request.object_key,
        )

        image_bytes = response.read()

    except S3Error as exc:
        logger.exception("MinIO evidence retrieval failed.")

        if exc.code in ("NoSuchKey", "NoSuchObject"):
            raise HTTPException(
                status_code=404,
                detail="Evidence image was not found in MinIO.",
            )

        raise HTTPException(
            status_code=503,
            detail="Evidence storage is temporarily unavailable.",
        )

    except Exception:
        logger.exception("Unexpected error retrieving evidence.")

        raise HTTPException(
            status_code=503,
            detail="Unable to retrieve evidence.",
        )

    finally:
        if response is not None:
            response.close()
            response.release_conn()

    try:
        detection_result = detect_number_plates(image_bytes)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except FileNotFoundError:
        logger.exception("License plate model is missing.")

        raise HTTPException(
            status_code=500,
            detail="License plate detection model is not installed.",
        )

    except Exception:
        logger.exception("Number plate detection failed.")

        raise HTTPException(
            status_code=500,
            detail="Number plate detection failed.",
        )

    return {
        "evidence_id": str(request.evidence_id),
        "estate_id": str(request.estate_id),
        "gate_id": str(request.gate_id),
        "status": "PROCESSED",
        "result": detection_result,
    }

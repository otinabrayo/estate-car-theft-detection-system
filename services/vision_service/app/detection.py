import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException       # type: ignore
from minio.error import S3Error                    # type: ignore
from pydantic import BaseModel, Field              # type: ignore

from .config import MINIO_BUCKET
from .storage import minio_client
from .detector import detect_vehicles


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/detection",
    tags=["Vehicle Detection"],
)


class VehicleDetectionRequest(BaseModel):
    evidence_id: UUID
    estate_id: UUID
    gate_id: UUID

    object_key: str = Field(
        min_length=1,
        max_length=1024,
    )


@router.post("/vehicles")
def detect_gate_vehicles(
    request: VehicleDetectionRequest,
):
    """
    Retrieve existing MinIO evidence and detect vehicles.
    """

    expected_prefix = (
        f"evidence/{request.estate_id}/"
        f"gates/{request.gate_id}/"
    )

    if not request.object_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=400,
            detail="Evidence object key does not match the supplied estate and gate.",
        )

    filename = request.object_key.rsplit("/", 1)[-1]

    if filename != f"{request.evidence_id}.jpg" and not (
        filename == f"{request.evidence_id}.jpeg"
        or filename == f"{request.evidence_id}.png"
        or filename == f"{request.evidence_id}.webp"
    ):
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
        detection_result = detect_vehicles(image_bytes)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception:
        logger.exception("Vehicle detection failed.")

        raise HTTPException(
            status_code=500,
            detail="Vehicle detection failed.",
        )

    return {
        "evidence_id": str(request.evidence_id),
        "estate_id": str(request.estate_id),
        "gate_id": str(request.gate_id),
        "status": "PROCESSED",
        "result": detection_result,
    }

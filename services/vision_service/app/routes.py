import logging
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status   # type: ignore
from PIL import Image, UnidentifiedImageError

from .config import MAX_IMAGE_SIZE_BYTES
from .storage import upload_evidence


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/evidence",
    tags=["Evidence"],
)

SUPPORTED_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


@router.post(
    "/images",
    status_code=status.HTTP_201_CREATED,
)
async def upload_gate_image(
    estate_id: UUID = Form(...),
    gate_id: UUID = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload an original gate-camera image to private MinIO storage.
    """

    # Read at most the configured limit plus one byte.
    image_bytes = await file.read(MAX_IMAGE_SIZE_BYTES + 1)

    if not image_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds the maximum allowed file size.",
        )

    # Validate the actual image content, not the filename.
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            image.verify()

    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid or unsupported image.",
        )

    if image_format not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=415,
            detail="Only JPEG, PNG and WEBP images are supported.",
        )

    content_type, extension = SUPPORTED_FORMATS[image_format]

    evidence_id = uuid4()
    uploaded_at = datetime.now(timezone.utc)

    # Never use a user-provided filename as the object key.
    object_key = (
        f"evidence/{estate_id}/"
        f"gates/{gate_id}/"
        f"{uploaded_at:%Y/%m/%d}/"
        f"{evidence_id}.{extension}"
    )

    try:
        storage_result = upload_evidence(
            object_key=object_key,
            image_bytes=image_bytes,
            content_type=content_type,
            metadata={
                "evidence-id": str(evidence_id),
                "estate-id": str(estate_id),
                "gate-id": str(gate_id),
            },
        )

    except Exception:
        logger.exception("Failed to upload gate evidence to MinIO.")

        raise HTTPException(
            status_code=503,
            detail="Evidence storage is temporarily unavailable.",
        )

    return {
        "evidence_id": str(evidence_id),
        "estate_id": str(estate_id),
        "gate_id": str(gate_id),
        "storage": "minio",
        "bucket": storage_result["bucket"],
        "object_key": storage_result["object_key"],
        "etag": storage_result["etag"],
        "content_type": content_type,
        "size_bytes": len(image_bytes),
        "uploaded_at": uploaded_at.isoformat(),
        "status": "STORED",
    }

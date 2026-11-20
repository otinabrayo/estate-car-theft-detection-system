import logging
import os
import tempfile

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import cv2    # type: ignore

from fastapi import APIRouter, File, Form, HTTPException, UploadFile   # type: ignore
from minio.error import S3Error   # type: ignore

from .config import (
    MINIO_BUCKET,
    MAX_VIDEO_SIZE_BYTES,
)
from .storage import ensure_bucket_exists, minio_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/evidence",
    tags=["Video Evidence"],
)

ALLOWED_VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
}


@router.post("/videos")
async def upload_cctv_video(
    estate_id: UUID = Form(...),
    gate_id: UUID = Form(...),
    file: UploadFile = File(...),
):
    extension = Path(file.filename or "").suffix.lower()

    if extension not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported video format. Use MP4, AVI or MOV.",
        )

    content_type = ALLOWED_VIDEO_TYPES[extension]

    video_bytes = await file.read(MAX_VIDEO_SIZE_BYTES + 1)

    if not video_bytes:
        raise HTTPException(
            status_code=400,
            detail="Uploaded video is empty.",
        )

    if len(video_bytes) > MAX_VIDEO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Video exceeds the configured maximum size.",
        )

    temporary_path = None
    capture = None

    try:
        # OpenCV needs a local file path for video validation.
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
                detail="OpenCV could not open the uploaded video.",
            )

        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = int(
            capture.get(cv2.CAP_PROP_FRAME_COUNT)
        )
        width = int(
            capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        height = int(
            capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

        success, first_frame = capture.read()

        if not success or first_frame is None:
            raise HTTPException(
                status_code=400,
                detail="Video does not contain a readable frame.",
            )

        if fps <= 0 or frame_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="Unable to determine video duration or frame rate.",
            )

        duration_seconds = frame_count / fps

    except HTTPException:
        raise

    except Exception:
        logger.exception("Video validation failed.")

        raise HTTPException(
            status_code=400,
            detail="Unable to validate uploaded video.",
        )

    finally:
        if capture is not None:
            capture.release()

        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)

    video_id = uuid4()

    now = datetime.now(timezone.utc)

    object_key = (
        f"videos/{estate_id}/gates/{gate_id}/"
        f"{now:%Y/%m/%d}/{video_id}{extension}"
    )

    try:
        ensure_bucket_exists()

        result = minio_client.put_object(
            bucket_name=MINIO_BUCKET,
            object_name=object_key,
            data=BytesIO(video_bytes),
            length=len(video_bytes),
            content_type=content_type,
            metadata={
                "video-id": str(video_id),
                "estate-id": str(estate_id),
                "gate-id": str(gate_id),
            },
        )

    except S3Error:
        logger.exception("Failed to store CCTV video in MinIO.")

        raise HTTPException(
            status_code=503,
            detail="Video storage is temporarily unavailable.",
        )

    except Exception:
        logger.exception("Unexpected video storage error.")

        raise HTTPException(
            status_code=500,
            detail="Unable to store CCTV video.",
        )

    return {
        "video_id": str(video_id),
        "estate_id": str(estate_id),
        "gate_id": str(gate_id),
        "storage": "minio",
        "bucket": MINIO_BUCKET,
        "object_key": object_key,
        "etag": result.etag,
        "content_type": content_type,
        "size_bytes": len(video_bytes),
        "video_metadata": {
            "width": width,
            "height": height,
            "fps": round(fps, 2),
            "frame_count": frame_count,
            "duration_seconds": round(duration_seconds, 2),
        },
        "uploaded_at": now.isoformat(),
        "status": "STORED",
    }

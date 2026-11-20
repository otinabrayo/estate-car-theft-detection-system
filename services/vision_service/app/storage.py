from minio import Minio          # type:ignore
from minio.error import S3Error  # type:ignore

from .config import (
    MINIO_ENDPOINT,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET,
    MINIO_SECURE,
)


minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)


def ensure_bucket_exists():
    """
    Create the evidence bucket if it does not exist.

    MinIO buckets are private by default.
    """
    if not minio_client.bucket_exists(MINIO_BUCKET):
        minio_client.make_bucket(MINIO_BUCKET)


def upload_evidence(
    object_key: str,
    image_bytes: bytes,
    content_type: str,
    metadata: dict | None = None,
):
    """
    Upload an evidence image to MinIO.
    """
    from io import BytesIO

    ensure_bucket_exists()

    result = minio_client.put_object(
        bucket_name=MINIO_BUCKET,
        object_name=object_key,
        data=BytesIO(image_bytes),
        length=len(image_bytes),
        content_type=content_type,
        metadata=metadata or {},
    )

    return {
        "bucket": MINIO_BUCKET,
        "object_key": object_key,
        "etag": result.etag,
        "version_id": result.version_id,
    }

from datetime import datetime, timezone

from fastapi import FastAPI   # type: ignore
from .detection import router as detection_router
from .routes import router as evidence_router
from .plate_detection import router as plate_detection_router
from .recognition import router as recognition_router
from .video_routes import router as video_router
from .video_processing import router as video_processing_router


app = FastAPI(
    title="Estate Car Theft Detection - Vision Service",
    description=(
        "Computer vision service for vehicle detection, "
        "number plate recognition and gate-camera evidence."
    ),
    version="1.0.0",
)

app.include_router(evidence_router)
app.include_router(detection_router)
app.include_router(plate_detection_router)
app.include_router(recognition_router)
app.include_router(video_router)
app.include_router(video_processing_router)

@app.get("/", tags=["System"])
async def root():
    return {
        "service": "estate-vision-service",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/health", tags=["System"])
async def health_check():
    return {
        "service": "estate-vision-service",
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

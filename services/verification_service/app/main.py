from contextlib import asynccontextmanager

from fastapi import FastAPI         # type: ignore
from redis.asyncio import Redis    # type: ignore

from .config import settings
from .redis_client import create_redis_client
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.SERVICE_NAME}...")

    redis_client = await create_redis_client(settings.REDIS_URL)
    app.state.redis = redis_client

    print("Redis connection established successfully.")

    try:
        yield
    finally:
        await redis_client.aclose()
        print("Redis connection closed.")
        print(f"Stopping {settings.SERVICE_NAME}...")


app = FastAPI(
    title="Estate Verification Engine",
    description=(
        "Verification and risk assessment service "
        "for the Estate Car Theft Detection System."
    ),
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.include_router(
    router,
    prefix="/api/v1",
)


@app.get("/")
async def root():
    return {
        "message": "Estate Verification Engine is running",
        "service": settings.SERVICE_NAME,
        "docs": "/docs",
        "health": "/api/v1/health/",
    }

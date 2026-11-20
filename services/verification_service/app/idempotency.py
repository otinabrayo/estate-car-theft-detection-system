import hashlib
import json
from uuid import UUID, uuid4

from fastapi import HTTPException, status    # type:ignore
from redis.asyncio import Redis              # type:ignore

from .schemas import GateRecognitionEvent, VerificationResponse   # type:ignore


RESULT_TTL_SECONDS = 86400
LOCK_TTL_SECONDS = 30


def event_fingerprint(event: GateRecognitionEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_keys(idempotency_key: UUID) -> tuple[str, str]:
    base = f"estate:verification:idempotency:{idempotency_key}"

    return f"{base}:result", f"{base}:lock"


async def get_cached_response(
    redis: Redis,
    result_key: str,
    fingerprint: str,
) -> VerificationResponse | None:
    cached = await redis.get(result_key)

    if cached is None:
        return None

    data = json.loads(cached)

    if data.get("fingerprint") != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different event.",
        )

    return VerificationResponse.model_validate(data["response"])


async def acquire_event_lock(
    redis: Redis,
    lock_key: str,
    fingerprint: str,
) -> str:
    token = str(uuid4())
    lock_value = f"{fingerprint}:{token}"

    acquired = await redis.set(
        lock_key,
        lock_value,
        nx=True,
        ex=LOCK_TTL_SECONDS,
    )

    if acquired:
        return token

    existing_lock = await redis.get(lock_key)

    if existing_lock:
        existing_fingerprint = existing_lock.split(":", 1)[0]

        if existing_fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key is being used by a different event.",
            )

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This event is already being processed. Retry shortly.",
    )


async def save_cached_response(
    redis: Redis,
    result_key: str,
    fingerprint: str,
    response: VerificationResponse,
) -> None:
    data = {
        "fingerprint": fingerprint,
        "response": response.model_dump(mode="json"),
    }

    await redis.set(
        result_key,
        json.dumps(data),
        ex=RESULT_TTL_SECONDS,
    )


async def release_event_lock(
    redis: Redis,
    lock_key: str,
    fingerprint: str,
    token: str,
) -> None:
    lock_value = f"{fingerprint}:{token}"

    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """

    await redis.eval(script, 1, lock_key, lock_value)

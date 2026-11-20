from redis.asyncio import Redis   # type: ignore


async def create_redis_client(redis_url: str) -> Redis:
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )

    try:
        await client.ping()
    except Exception:
        await client.aclose()
        raise

    return client

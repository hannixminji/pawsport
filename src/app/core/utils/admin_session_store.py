from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

pool: ConnectionPool | None = None
client: Redis | None = None


async def async_get_admin_redis() -> AsyncGenerator[Redis, None]:
    if pool is None:
        raise RuntimeError("Admin Redis pool not initialized")

    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.aclose()  # type: ignore

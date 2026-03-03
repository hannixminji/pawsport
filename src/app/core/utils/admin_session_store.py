from collections.abc import AsyncGenerator

from redis.asyncio import ConnectionPool, Redis

pool: ConnectionPool | None = None
client: Redis | None = None


async def async_get_admin_redis() -> AsyncGenerator[Redis]:
    if client is None:
        raise RuntimeError("Admin Redis client not initialized")

    yield client

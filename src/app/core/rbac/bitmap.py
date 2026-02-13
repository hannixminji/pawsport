# rbac_bitmap_cache.py
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models._rbac_tables import role_permission
from app.models.permission import Permission

LOGGER = logging.getLogger(__name__)

PERM_BM_PREFIX: Final[str] = "perm_bm"
ROLESET_VER_PREFIX: Final[str] = "roleset_ver:"
ROLE_ROLESETS_PREFIX: Final[str] = "role_rolesets:"
PERM_SCHEMA_VERSION_KEY: Final[str] = "perm_schema_version"

ROLESET_BITMAP_TTL_SECONDS: Final[int] = 1800
ROLESET_INDEX_TTL_SECONDS: Final[int] = 604800
REBUILD_LOCK_TTL_SECONDS: Final[int] = 10
REBUILD_LOCK_WAIT_SECONDS: Final[float] = 2.0
REBUILD_VERSION_RETRIES: Final[int] = 3

TMP_KEY_TTL_SECONDS: Final[int] = 60

DELETE_LOCK_LUA: Final[str] = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""


@dataclass(frozen=True, slots=True)
class PermissionIndex:
    by_key: dict[str, int]
    by_id: dict[int, int]


async def _get_int(redis: Redis, key: str) -> int:
    v = await redis.get(key)
    if not v:
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


async def get_schema_version(redis: Redis) -> int:
    return await _get_int(redis, PERM_SCHEMA_VERSION_KEY)


async def get_roleset_version(redis: Redis, roles_hash: str) -> int:
    return await _get_int(redis, f"{ROLESET_VER_PREFIX}{roles_hash}")


async def load_permission_index(db: AsyncSession) -> PermissionIndex:
    rows = (await db.execute(select(Permission.id, Permission.key, Permission.bit_index))).all()

    by_key: dict[str, int] = {}
    by_id: dict[int, int] = {}

    for pid, key, bit in rows:
        if bit is None:
            raise RuntimeError(f"Permission {key} missing bit_index")
        by_key[str(key)] = int(bit)
        by_id[int(pid)] = int(bit)

    return PermissionIndex(by_key=by_key, by_id=by_id)


def compute_roles_hash(role_ids: set[int]) -> str:
    payload = ",".join(map(str, sorted(role_ids))).encode()
    return hashlib.sha256(payload).hexdigest()


def roleset_bitmap_key(*, schema_version: int, roles_hash: str, version: int) -> str:
    return f"{PERM_BM_PREFIX}:s{schema_version}:{roles_hash}:v{version}"


async def ensure_roleset_indexed(redis: Redis, role_ids: set[int], roles_hash: str) -> None:
    """
    Reverse-index roles -> roles_hashes and ensure the roleset version key exists with TTL.

    Important: EXPIRE on a missing key is a no-op in Redis.
    We SETNX the version key to guarantee TTL is actually applied, and INCR works later.
    """
    pipe = redis.pipeline(transaction=False)

    for rid in role_ids:
        rkey = f"{ROLE_ROLESETS_PREFIX}{rid}"
        pipe.sadd(rkey, roles_hash)
        pipe.expire(rkey, ROLESET_INDEX_TTL_SECONDS)

    ver_key = f"{ROLESET_VER_PREFIX}{roles_hash}"
    pipe.setnx(ver_key, 0)
    pipe.expire(ver_key, ROLESET_INDEX_TTL_SECONDS)

    await pipe.execute()


async def acquire_lock(redis: Redis, lock_key: str) -> str | None:
    token = str(uuid.uuid4())
    ok = await redis.set(lock_key, token, nx=True, ex=REBUILD_LOCK_TTL_SECONDS)
    return token if ok else None


async def rebuild_roleset_bitmap(
    db: AsyncSession,
    redis: Redis,
    perm_index: PermissionIndex,
    role_ids: Iterable[int],
) -> None:
    ids_set = {int(r) for r in role_ids}
    if not ids_set:
        return

    roles_hash = compute_roles_hash(ids_set)
    await ensure_roleset_indexed(redis, ids_set, roles_hash)

    lock_key = f"{PERM_BM_PREFIX}:lock:{roles_hash}"
    token = await acquire_lock(redis, lock_key)

    if token is None:
        deadline = time.monotonic() + REBUILD_LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            schema_version = await get_schema_version(redis)
            version = await get_roleset_version(redis, roles_hash)

            key = roleset_bitmap_key(schema_version=schema_version, roles_hash=roles_hash, version=version)
            if await redis.exists(key):
                return

            await asyncio.sleep(0.05)

        token = await acquire_lock(redis, lock_key)
        if token is None:
            return

    tmp = f"{PERM_BM_PREFIX}:tmp:{roles_hash}:{uuid.uuid4()}"

    try:
        schema_before = await get_schema_version(redis)
        version_before = await get_roleset_version(redis, roles_hash)

        perm_ids = (
            await db.execute(
                select(role_permission.c.permission_id).where(role_permission.c.role_id.in_(sorted(ids_set)))
            )
        ).scalars().all()

        pipe = redis.pipeline(transaction=True)
        pipe.setbit(tmp, 0, 0)
        pipe.expire(tmp, TMP_KEY_TTL_SECONDS)

        for pid in perm_ids:
            bit = perm_index.by_id.get(int(pid))
            if bit is not None:
                pipe.setbit(tmp, bit, 1)

        final_key = roleset_bitmap_key(schema_version=schema_before, roles_hash=roles_hash, version=version_before)
        pipe.rename(tmp, final_key)
        pipe.expire(final_key, ROLESET_BITMAP_TTL_SECONDS)

        await pipe.execute()

        schema_after = await get_schema_version(redis)
        version_after = await get_roleset_version(redis, roles_hash)

        if schema_after != schema_before or version_after != version_before:
            await redis.delete(final_key)

    finally:
        try:
            await redis.eval(DELETE_LOCK_LUA, 1, lock_key, token)
        except Exception:
            LOGGER.exception("Failed to release rebuild lock")


async def roleset_has_permission(
    db: AsyncSession,
    redis: Redis,
    perm_index: PermissionIndex,
    role_ids: Iterable[int],
    permission_key: str,
) -> bool:
    bit = perm_index.by_key.get(permission_key)
    if bit is None:
        return False

    ids_set = {int(r) for r in role_ids}
    if not ids_set:
        return False

    roles_hash = compute_roles_hash(ids_set)
    await ensure_roleset_indexed(redis, ids_set, roles_hash)

    for _ in range(REBUILD_VERSION_RETRIES):
        schema_version = await get_schema_version(redis)
        version = await get_roleset_version(redis, roles_hash)

        key = roleset_bitmap_key(schema_version=schema_version, roles_hash=roles_hash, version=version)

        pipe = redis.pipeline(transaction=False)
        pipe.exists(key)
        pipe.getbit(key, int(bit))
        exists, bitval = await pipe.execute()

        if exists:
            return bool(bitval)

        await rebuild_roleset_bitmap(db, redis, perm_index, ids_set)

    schema_version = await get_schema_version(redis)
    version = await get_roleset_version(redis, roles_hash)
    final_key = roleset_bitmap_key(schema_version=schema_version, roles_hash=roles_hash, version=version)

    if not await redis.exists(final_key):
        LOGGER.error("RBAC bitmap missing after retries: %s", final_key)
        return False

    return bool(await redis.getbit(final_key, int(bit)))


async def on_role_permission_changed(redis: Redis, role_id: int) -> None:
    rkey = f"{ROLE_ROLESETS_PREFIX}{int(role_id)}"
    roles_hashes = await redis.smembers(rkey)
    if not roles_hashes:
        return

    pipe = redis.pipeline(transaction=False)
    for rh in roles_hashes:
        roles_hash = rh.decode() if isinstance(rh, (bytes, bytearray)) else str(rh)
        ver_key = f"{ROLESET_VER_PREFIX}{roles_hash}"
        pipe.incr(ver_key)
        pipe.expire(ver_key, ROLESET_INDEX_TTL_SECONDS)

    await pipe.execute()


async def on_permission_schema_changed(redis: Redis) -> None:
    await redis.incr(PERM_SCHEMA_VERSION_KEY)

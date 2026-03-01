import asyncio
import hashlib
import logging
import time
import uuid
import weakref
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models._rbac_table import admin_role_permission
from ...models.admin_permission import AdminPermission

LOGGER = logging.getLogger(__name__)

PERM_BM_PREFIX: Final[str] = "perm_bm"
ROLESET_VER_PREFIX: Final[str] = "roleset_ver:"
ROLE_ROLESETS_PREFIX: Final[str] = "role_rolesets:"
PERM_SCHEMA_VERSION_KEY: Final[str] = "perm_schema_version"

ROLESET_BITMAP_TTL_SECONDS: Final[int] = 1800
ROLESET_INDEX_TTL_SECONDS: Final[int] = 604800
REBUILD_LOCK_TTL_SECONDS: Final[int] = 30
REBUILD_LOCK_WAIT_SECONDS: Final[float] = 2.0
REBUILD_VERSION_RETRIES: Final[int] = 3
REBUILD_RETRY_BASE_DELAY: Final[float] = 0.05
PERMISSION_CHECK_TIMEOUT_SECONDS: Final[float] = 10.0

TMP_KEY_TTL_SECONDS: Final[int] = 60

DELETE_LOCK_LUA: Final[str] = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""

INCR_AND_RENAME_LUA: Final[str] = """
if redis.call("exists", KEYS[2]) == 0 then
  return redis.error_reply("ERR tmp key missing")
end
local new_version = redis.call("incr", KEYS[1])
redis.call("expire", KEYS[1], tonumber(ARGV[3]))
local final_key = ARGV[4] .. ":s" .. ARGV[1] .. ":" .. ARGV[2] .. ":v" .. tostring(new_version)
redis.call("rename", KEYS[2], final_key)
redis.call("expire", final_key, tonumber(ARGV[5]))
return new_version
"""

_process_rebuild_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)


def _get_process_lock(roles_hash: str) -> asyncio.Lock:
    lock = _process_rebuild_locks.get(roles_hash)
    if lock is None:
        lock = asyncio.Lock()
        _process_rebuild_locks[roles_hash] = lock
    return lock


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


async def _fetch_versions(redis: Redis, roles_hash: str) -> tuple[int, int]:
    schema_version, version = await asyncio.gather(
        get_schema_version(redis),
        get_roleset_version(redis, roles_hash),
    )
    return schema_version, version


async def load_permission_index(db: AsyncSession) -> PermissionIndex:
    rows = (await db.execute(select(AdminPermission.id, AdminPermission.key, AdminPermission.bit_index))).all()

    by_key: dict[str, int] = {}
    by_id: dict[int, int] = {}

    for pid, key, bit in rows:
        if bit is None:
            raise RuntimeError(f"Permission id={pid} key={key} missing bit_index")
        by_key[str(key)] = int(bit)
        by_id[int(pid)] = int(bit)

    return PermissionIndex(by_key=by_key, by_id=by_id)


def compute_roles_hash(role_ids: set[int]) -> str:
    payload = ",".join(map(str, sorted(role_ids))).encode()
    return hashlib.sha256(payload).hexdigest()


def roleset_bitmap_key(*, schema_version: int, roles_hash: str, version: int) -> str:
    return f"{PERM_BM_PREFIX}:s{schema_version}:{roles_hash}:v{version}"


async def ensure_roleset_indexed(redis: Redis, role_ids: set[int], roles_hash: str) -> None:
    if not role_ids:
        return

    pipe = redis.pipeline(transaction=False)

    for rid in role_ids:
        rkey = f"{ROLE_ROLESETS_PREFIX}{rid}"
        pipe.sadd(rkey, roles_hash)
        pipe.expire(rkey, ROLESET_INDEX_TTL_SECONDS)

    ver_key = f"{ROLESET_VER_PREFIX}{roles_hash}"
    pipe.set(ver_key, 0, nx=True, ex=ROLESET_INDEX_TTL_SECONDS)
    pipe.expire(ver_key, ROLESET_INDEX_TTL_SECONDS)

    await pipe.execute()


async def acquire_lock(redis: Redis, lock_key: str) -> str | None:
    token = str(uuid.uuid4())
    ok = await redis.set(lock_key, token, nx=True, ex=REBUILD_LOCK_TTL_SECONDS)
    return token if ok else None


async def _check_bitmap(
    redis: Redis,
    roles_hash: str,
    bit: int,
) -> tuple[bool, bool]:
    schema_version, version = await _fetch_versions(redis, roles_hash)
    key = roleset_bitmap_key(schema_version=schema_version, roles_hash=roles_hash, version=version)
    pipe = redis.pipeline(transaction=False)
    pipe.exists(key)
    pipe.getbit(key, bit)
    exists, bitval = await pipe.execute()
    return bool(exists), bool(bitval)


async def _rebuild_roleset_bitmap(
    db: AsyncSession,
    redis: Redis,
    perm_index: PermissionIndex,
    ids_set: set[int],
    roles_hash: str,
) -> None:
    lock_key = f"{PERM_BM_PREFIX}:lock:{roles_hash}"
    token = await acquire_lock(redis, lock_key)

    if token is None:
        deadline = time.monotonic() + REBUILD_LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            schema_version, version = await _fetch_versions(redis, roles_hash)
            if await redis.exists(
                roleset_bitmap_key(
                    schema_version=schema_version,
                    roles_hash=roles_hash,
                    version=version,
                )
            ):
                return
            await asyncio.sleep(0.05)

        token = await acquire_lock(redis, lock_key)
        if token is None:
            LOGGER.warning("Failed to acquire rebuild lock after wait: %s", lock_key)
            return

    tmp = f"{PERM_BM_PREFIX}:tmp:{roles_hash}:{uuid.uuid4()}"

    try:
        schema_version, version = await _fetch_versions(redis, roles_hash)

        if await redis.exists(
            roleset_bitmap_key(
                schema_version=schema_version,
                roles_hash=roles_hash,
                version=version,
            )
        ):
            return

        ver_key = f"{ROLESET_VER_PREFIX}{roles_hash}"

        perm_ids = (
            await db.execute(
                select(admin_role_permission.c.permission_id).where(
                    admin_role_permission.c.role_id.in_(ids_set)
                )
            )
        ).scalars().all()

        pipe = redis.pipeline(transaction=True)
        pipe.setbit(tmp, 0, 0)
        pipe.expire(tmp, TMP_KEY_TTL_SECONDS)

        for pid in perm_ids:
            bit = perm_index.by_id.get(int(pid))
            if bit is not None:
                pipe.setbit(tmp, bit, 1)

        await pipe.execute()

        await redis.eval(
            INCR_AND_RENAME_LUA,
            2,
            ver_key,
            tmp,
            str(schema_version),
            roles_hash,
            str(ROLESET_INDEX_TTL_SECONDS),
            PERM_BM_PREFIX,
            str(ROLESET_BITMAP_TTL_SECONDS),
        )

    except Exception:
        LOGGER.exception("Bitmap rebuild failed for roles_hash=%s", roles_hash)
        try:
            await redis.delete(tmp)
        except Exception:
            pass

    finally:
        try:
            await redis.eval(DELETE_LOCK_LUA, 1, lock_key, token)
        except Exception:
            LOGGER.exception("Failed to release rebuild lock %s", lock_key)


async def rebuild_roleset_bitmap(
    db: AsyncSession,
    redis: Redis,
    perm_index: PermissionIndex,
    role_ids: set[int],
) -> None:
    if not role_ids:
        return

    roles_hash = compute_roles_hash(role_ids)
    await ensure_roleset_indexed(redis, role_ids, roles_hash)
    await _rebuild_roleset_bitmap(db, redis, perm_index, role_ids, roles_hash)


async def roleset_has_permission(
    db: AsyncSession,
    redis: Redis,
    perm_index: PermissionIndex,
    role_ids: set[int],
    permission_key: str,
) -> bool:
    bit = perm_index.by_key.get(permission_key)
    if bit is None or not role_ids:
        return False

    roles_hash = compute_roles_hash(role_ids)

    async with asyncio.timeout(PERMISSION_CHECK_TIMEOUT_SECONDS):
        exists, bitval = await _check_bitmap(redis, roles_hash, int(bit))
        if exists:
            return bitval

        await ensure_roleset_indexed(redis, role_ids, roles_hash)

        async with _get_process_lock(roles_hash):
            exists, bitval = await _check_bitmap(redis, roles_hash, int(bit))
            if exists:
                return bitval

            for attempt in range(REBUILD_VERSION_RETRIES):
                try:
                    await _rebuild_roleset_bitmap(db, redis, perm_index, role_ids, roles_hash)
                except Exception:
                    LOGGER.exception(
                        "Rebuild attempt %d/%d failed for roles_hash=%s",
                        attempt + 1,
                        REBUILD_VERSION_RETRIES,
                        roles_hash,
                    )
                    if attempt < REBUILD_VERSION_RETRIES - 1:
                        await asyncio.sleep(REBUILD_RETRY_BASE_DELAY * (2**attempt))
                    continue

                exists, bitval = await _check_bitmap(redis, roles_hash, int(bit))
                if exists:
                    return bitval

            LOGGER.error(
                "RBAC bitmap missing after %d retries for roles_hash=%s",
                REBUILD_VERSION_RETRIES,
                roles_hash,
            )
            return False


async def on_role_permission_changed(redis: Redis, role_id: int) -> None:
    rkey = f"{ROLE_ROLESETS_PREFIX}{int(role_id)}"
    roles_hashes = await redis.smembers(rkey)
    if not roles_hashes:
        return

    pipe = redis.pipeline(transaction=False)
    for rh in roles_hashes:
        roles_hash = rh if isinstance(rh, str) else rh.decode()
        ver_key = f"{ROLESET_VER_PREFIX}{roles_hash}"
        pipe.incr(ver_key)
        pipe.expire(ver_key, ROLESET_INDEX_TTL_SECONDS)

    await pipe.execute()


async def on_permission_schema_changed(redis: Redis) -> None:
    await redis.incr(PERM_SCHEMA_VERSION_KEY)

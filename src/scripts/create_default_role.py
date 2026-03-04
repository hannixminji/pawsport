import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db.database import AsyncSession, local_session
from app.models.admin_permission import AdminPermission
from app.models.admin_role import AdminRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_ROLE_NAME = "Default Role"
DEFAULT_ROLE_DESCRIPTION = "Default role with full access to all api/v1/app endpoints."

# Permission keys that correspond to what api/v1/app exposes.
# This excludes superuser-only operations (hard delete, bulk hard delete)
# and admin-only resources (rate_limits, tiers).
DEFAULT_ROLE_PERMISSION_KEYS: list[str] = [
    # ── dashboards ──
    "dashboard:read",

    # ── articles (read-only in app) ──
    "article:read",

    # ── missing reports ──
    "missing_report:search",
    "missing_report:create",
    "missing_report:read",
    "missing_report:soft_delete",
    "missing_report:update_status",
    "missing_report:update",

    # ── mobile users ──
    "mobile_user:create",
    "mobile_user:search",
    "mobile_user:read",
    "mobile_user:update_password",
    "mobile_user:update_tier",
    "mobile_user:update",

    # ── pet allergies ──
    "pet_allergy:search",
    "pet_allergy:create",
    "pet_allergy:read",
    "pet_allergy:soft_delete",
    "pet_allergy:update",

    # ── pet inventories ──
    "pet_inventory:search",
    "pet_inventory:create",
    "pet_inventory:read",
    "pet_inventory:soft_delete",
    "pet_inventory:update",

    # ── pet medical conditions ──
    "pet_medical_condition:search",
    "pet_medical_condition:create",
    "pet_medical_condition:read",
    "pet_medical_condition:soft_delete",
    "pet_medical_condition:update",

    # ── pet medications ──
    "pet_medication:search",
    "pet_medication:create",
    "pet_medication:read",
    "pet_medication:soft_delete",
    "pet_medication:update",

    # ── pet schedules ──
    "pet_schedule:search",
    "pet_schedule:create",
    "pet_schedule:read",
    "pet_schedule:soft_delete",
    "pet_schedule:update",

    # ── pet vaccination records ──
    "pet_vaccination_record:search",
    "pet_vaccination_record:create",
    "pet_vaccination_record:read",
    "pet_vaccination_record:soft_delete",
    "pet_vaccination_record:update",

    # ── pets ──
    "pet:search",
    "pet:create",
    "pet:read",
    "pet:soft_delete",
    "pet:update",

    # ── sighting reports ──
    "sighting_report:search",
    "sighting_report:create",
    "sighting_report:read",
    "sighting_report:soft_delete",
    "sighting_report:update",
]


async def create_default_role(session: AsyncSession) -> None:
    existing_role = await session.scalar(
        select(AdminRole)
        .options(selectinload(AdminRole.permissions))
        .where(AdminRole.name == DEFAULT_ROLE_NAME)
    )

    permissions = (
        await session.scalars(
            select(AdminPermission)
            .where(AdminPermission.key.in_(DEFAULT_ROLE_PERMISSION_KEYS))
        )
    ).all()

    found_keys = {permission.key for permission in permissions}
    missing_keys = set(DEFAULT_ROLE_PERMISSION_KEYS) - found_keys
    if missing_keys:
        logger.warning(
            "The following permission keys were not found in the database and will be skipped: %s. "
            "Run seed_permissions first.",
            sorted(missing_keys),
        )

    if existing_role is not None:
        logger.info(
            "Role '%s' already exists (id=%d). Syncing permissions...",
            DEFAULT_ROLE_NAME,
            existing_role.id,
        )
        role = existing_role
        role.permissions.clear()
        role.permissions.extend(permissions)
    else:
        role = AdminRole(name=DEFAULT_ROLE_NAME, description=DEFAULT_ROLE_DESCRIPTION)
        session.add(role)
        role.permissions.extend(permissions)
        await session.flush()
        logger.info("Created role '%s' (id=%d).", DEFAULT_ROLE_NAME, role.id)

    try:
        await session.commit()
        logger.info(
            "Role '%s' now has %d permissions assigned.",
            DEFAULT_ROLE_NAME,
            len(permissions),
        )

    except Exception:
        await session.rollback()
        logger.exception("Failed to create/update role '%s'.", DEFAULT_ROLE_NAME)
        raise


async def main() -> None:
    async with local_session() as session:
        await create_default_role(session)


if __name__ == "__main__":
    asyncio.run(main())

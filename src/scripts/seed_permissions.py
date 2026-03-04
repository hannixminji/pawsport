import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.db.database import AsyncSession, local_session
from app.models.admin_permission import AdminPermission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PERMISSIONS: list[dict[str, str]] = [
    # ── dashboards ──
    {
        "key": "dashboard:read",
        "name": "Read Dashboard",
        "description": "View dashboard statistics",
    },

    # ── articles ──
    {
        "key": "article:create",
        "name": "Create Article",
        "description": "Create a new article",
    },
    {
        "key": "article:search",
        "name": "Search Articles",
        "description": "Search articles",
    },
    {
        "key": "article:read",
        "name": "Read Article",
        "description": "View articles",
    },
    {
        "key": "article:bulk_soft_delete",
        "name": "Bulk Soft Delete Articles",
        "description": "Soft-delete multiple articles",
    },
    {
        "key": "article:soft_delete",
        "name": "Soft Delete Article",
        "description": "Soft-delete an article",
    },
    {
        "key": "article:update",
        "name": "Update Article",
        "description": "Update an article",
    },

    # ── missing reports ──
    {
        "key": "missing_report:search",
        "name": "Search Missing Reports",
        "description": "Search missing reports",
    },
    {
        "key": "missing_report:create",
        "name": "Create Missing Report",
        "description": "Create a missing report",
    },
    {
        "key": "missing_report:read",
        "name": "Read Missing Report",
        "description": "View missing reports",
    },
    {
        "key": "missing_report:soft_delete",
        "name": "Soft Delete Missing Report",
        "description": "Soft-delete a missing report",
    },
    {
        "key": "missing_report:update_status",
        "name": "Update Missing Report Status",
        "description": "Update missing report status",
    },
    {
        "key": "missing_report:update",
        "name": "Update Missing Report",
        "description": "Update a missing report",
    },

    # ── mobile users ──
    {
        "key": "mobile_user:create",
        "name": "Create Mobile User",
        "description": "Create a mobile user",
    },
    {
        "key": "mobile_user:search",
        "name": "Search Mobile Users",
        "description": "Search mobile users",
    },
    {
        "key": "mobile_user:read",
        "name": "Read Mobile User",
        "description": "View mobile users",
    },
    {
        "key": "mobile_user:soft_delete",
        "name": "Soft Delete Mobile User",
        "description": "Soft-delete a mobile user",
    },
    {
        "key": "mobile_user:update_password",
        "name": "Update Mobile User Password",
        "description": "Update a mobile user password",
    },
    {
        "key": "mobile_user:update_tier",
        "name": "Update Mobile User Tier",
        "description": "Update a mobile user tier",
    },
    {
        "key": "mobile_user:update_account_status",
        "name": "Update Mobile User Account Status",
        "description": "Update a mobile user account status",
    },
    {
        "key": "mobile_user:update",
        "name": "Update Mobile User",
        "description": "Update a mobile user",
    },

    # ── pet allergies ──
    {
        "key": "pet_allergy:search",
        "name": "Search Pet Allergies",
        "description": "Search pet allergies",
    },
    {
        "key": "pet_allergy:create",
        "name": "Create Pet Allergy",
        "description": "Create a pet allergy",
    },
    {
        "key": "pet_allergy:read",
        "name": "Read Pet Allergy",
        "description": "View pet allergies",
    },
    {
        "key": "pet_allergy:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Allergies",
        "description": "Soft-delete multiple pet allergies",
    },
    {
        "key": "pet_allergy:soft_delete",
        "name": "Soft Delete Pet Allergy",
        "description": "Soft-delete a pet allergy",
    },
    {
        "key": "pet_allergy:update",
        "name": "Update Pet Allergy",
        "description": "Update a pet allergy",
    },

    # ── pet inventories ──
    {
        "key": "pet_inventory:search",
        "name": "Search Pet Inventory",
        "description": "Search pet inventory",
    },
    {
        "key": "pet_inventory:create",
        "name": "Create Pet Inventory",
        "description": "Create a pet inventory item",
    },
    {
        "key": "pet_inventory:read",
        "name": "Read Pet Inventory",
        "description": "View pet inventory",
    },
    {
        "key": "pet_inventory:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Inventory",
        "description": "Soft-delete multiple pet inventory items",
    },
    {
        "key": "pet_inventory:soft_delete",
        "name": "Soft Delete Pet Inventory",
        "description": "Soft-delete a pet inventory item",
    },
    {
        "key": "pet_inventory:update",
        "name": "Update Pet Inventory",
        "description": "Update a pet inventory item",
    },

    # ── pet medical conditions ──
    {
        "key": "pet_medical_condition:search",
        "name": "Search Pet Medical Conditions",
        "description": "Search pet medical conditions",
    },
    {
        "key": "pet_medical_condition:create",
        "name": "Create Pet Medical Condition",
        "description": "Create a pet medical condition",
    },
    {
        "key": "pet_medical_condition:read",
        "name": "Read Pet Medical Condition",
        "description": "View pet medical conditions",
    },
    {
        "key": "pet_medical_condition:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Medical Conditions",
        "description": "Soft-delete multiple pet medical conditions",
    },
    {
        "key": "pet_medical_condition:soft_delete",
        "name": "Soft Delete Pet Medical Condition",
        "description": "Soft-delete a pet medical condition",
    },
    {
        "key": "pet_medical_condition:update",
        "name": "Update Pet Medical Condition",
        "description": "Update a pet medical condition",
    },

    # ── pet medications ──
    {
        "key": "pet_medication:search",
        "name": "Search Pet Medications",
        "description": "Search pet medications",
    },
    {
        "key": "pet_medication:create",
        "name": "Create Pet Medication",
        "description": "Create a pet medication",
    },
    {
        "key": "pet_medication:read",
        "name": "Read Pet Medication",
        "description": "View pet medications",
    },
    {
        "key": "pet_medication:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Medications",
        "description": "Soft-delete multiple pet medications",
    },
    {
        "key": "pet_medication:soft_delete",
        "name": "Soft Delete Pet Medication",
        "description": "Soft-delete a pet medication",
    },
    {
        "key": "pet_medication:update",
        "name": "Update Pet Medication",
        "description": "Update a pet medication",
    },

    # ── pet schedules ──
    {
        "key": "pet_schedule:search",
        "name": "Search Pet Schedules",
        "description": "Search pet schedules",
    },
    {
        "key": "pet_schedule:create",
        "name": "Create Pet Schedule",
        "description": "Create a pet schedule",
    },
    {
        "key": "pet_schedule:read",
        "name": "Read Pet Schedule",
        "description": "View pet schedules",
    },
    {
        "key": "pet_schedule:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Schedules",
        "description": "Soft-delete multiple pet schedules",
    },
    {
        "key": "pet_schedule:soft_delete",
        "name": "Soft Delete Pet Schedule",
        "description": "Soft-delete a pet schedule",
    },
    {
        "key": "pet_schedule:update",
        "name": "Update Pet Schedule",
        "description": "Update a pet schedule",
    },

    # ── pet vaccination records ──
    {
        "key": "pet_vaccination_record:search",
        "name": "Search Pet Vaccination Records",
        "description": "Search pet vaccination records",
    },
    {
        "key": "pet_vaccination_record:create",
        "name": "Create Pet Vaccination Record",
        "description": "Create a pet vaccination record",
    },
    {
        "key": "pet_vaccination_record:read",
        "name": "Read Pet Vaccination Record",
        "description": "View pet vaccination records",
    },
    {
        "key": "pet_vaccination_record:bulk_soft_delete",
        "name": "Bulk Soft Delete Pet Vaccination Records",
        "description": "Soft-delete multiple pet vaccination records",
    },
    {
        "key": "pet_vaccination_record:soft_delete",
        "name": "Soft Delete Pet Vaccination Record",
        "description": "Soft-delete a pet vaccination record",
    },
    {
        "key": "pet_vaccination_record:update",
        "name": "Update Pet Vaccination Record",
        "description": "Update a pet vaccination record",
    },

    # ── pets ──
    {
        "key": "pet:search",
        "name": "Search Pets",
        "description": "Search pets",
    },
    {
        "key": "pet:create",
        "name": "Create Pet",
        "description": "Create a pet",
    },
    {
        "key": "pet:read",
        "name": "Read Pet",
        "description": "View pets",
    },
    {
        "key": "pet:bulk_soft_delete",
        "name": "Bulk Soft Delete Pets",
        "description": "Soft-delete multiple pets",
    },
    {
        "key": "pet:soft_delete",
        "name": "Soft Delete Pet",
        "description": "Soft-delete a pet",
    },
    {
        "key": "pet:update",
        "name": "Update Pet",
        "description": "Update a pet",
    },

    # ── sighting reports ──
    {
        "key": "sighting_report:search",
        "name": "Search Sighting Reports",
        "description": "Search sighting reports",
    },
    {
        "key": "sighting_report:create",
        "name": "Create Sighting Report",
        "description": "Create a sighting report",
    },
    {
        "key": "sighting_report:read",
        "name": "Read Sighting Report",
        "description": "View sighting reports",
    },
    {
        "key": "sighting_report:soft_delete",
        "name": "Soft Delete Sighting Report",
        "description": "Soft-delete a sighting report",
    },
    {
        "key": "sighting_report:update",
        "name": "Update Sighting Report",
        "description": "Update a sighting report",
    },

    # ── tiers ──
    {
        "key": "tier:create",
        "name": "Create Tier",
        "description": "Create a tier",
    },
    {
        "key": "tier:search",
        "name": "Search Tiers",
        "description": "Search tiers",
    },
    {
        "key": "tier:read",
        "name": "Read Tier",
        "description": "View tiers",
    },
    {
        "key": "tier:update",
        "name": "Update Tier",
        "description": "Update a tier",
    },

    # ── rate limits ──
    {
        "key": "rate_limit:search",
        "name": "Search Rate Limits",
        "description": "Search rate limits",
    },
    {
        "key": "rate_limit:create",
        "name": "Create Rate Limit",
        "description": "Create a rate limit",
    },
    {
        "key": "rate_limit:read",
        "name": "Read Rate Limit",
        "description": "View rate limits",
    },
    {
        "key": "rate_limit:bulk_soft_delete",
        "name": "Bulk Soft Delete Rate Limits",
        "description": "Soft-delete multiple rate limits",
    },
    {
        "key": "rate_limit:soft_delete",
        "name": "Soft Delete Rate Limit",
        "description": "Soft-delete a rate limit",
    },
    {
        "key": "rate_limit:update",
        "name": "Update Rate Limit",
        "description": "Update a rate limit",
    },
]


async def seed_permissions(session: AsyncSession) -> None:
    if not PERMISSIONS:
        logger.info("No permissions defined. Skipping.")
        return

    stmt = pg_insert(AdminPermission).values(PERMISSIONS)
    stmt = stmt.on_conflict_do_nothing(index_elements=["key"])

    try:
        await session.execute(stmt)
        await session.commit()
        logger.info("Permissions seeding complete (duplicates skipped automatically).")
    except Exception:
        await session.rollback()
        logger.exception("Failed to seed permissions.")
        raise


async def main() -> None:
    async with local_session() as session:
        await seed_permissions(session)


if __name__ == "__main__":
    asyncio.run(main())

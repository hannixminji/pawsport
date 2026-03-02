import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import MissingReportStatus
from ..core.health import check_database_health, check_redis_health
from ..models.admin_user import AdminUser
from ..models.missing_report import MissingReport
from ..models.mobile_user import MobileUser
from ..models.pet import Pet
from ..models.sighting_report import SightingReport

LOGGER = logging.getLogger(__name__)

MISSING_REPORT_DASHBOARD_STATUSES: list[MissingReportStatus] = [
    MissingReportStatus.LOST,
    MissingReportStatus.FOUND,
    MissingReportStatus.RETURNED,
    MissingReportStatus.FOSTERED,
]


@dataclass(slots=True)
class DashboardService:
    db: AsyncSession
    redis: Redis | None = None

    async def get_total_mobile_users(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(MobileUser)
                .where(MobileUser.is_deleted.is_(False))
            )
        ).scalar_one()

    async def get_total_admin_users(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(AdminUser)
                .where(AdminUser.is_deleted.is_(False))
            )
        ).scalar_one()

    async def get_total_pets(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(Pet)
                .where(Pet.is_deleted.is_(False))
            )
        ).scalar_one()

    async def get_total_missing_reports(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(MissingReport)
                .where(MissingReport.is_deleted.is_(False))
            )
        ).scalar_one()

    async def get_missing_reports_by_status(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(MissingReport.report_status, func.count())
                .where(
                    MissingReport.is_deleted.is_(False),
                    MissingReport.report_status.in_(MISSING_REPORT_DASHBOARD_STATUSES),
                )
                .group_by(MissingReport.report_status)
            )
        ).all()

        result = {status.value: 0 for status in MISSING_REPORT_DASHBOARD_STATUSES}
        for status, count in rows:
            result[status.value] = count
        return result

    async def get_total_sighting_reports(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(SightingReport)
                .where(SightingReport.is_deleted.is_(False))
            )
        ).scalar_one()

    async def get_user_pets_count(self, user_id: int) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(Pet)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalar_one()

    async def get_user_missing_reports_count(self, user_id: int) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(MissingReport)
                .join(Pet, MissingReport.pet_id == Pet.id)
                .where(
                    Pet.owner_id == user_id,
                    MissingReport.is_deleted.is_(False),
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalar_one()

    async def get_user_sighting_reports_count(self, user_id: int) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(SightingReport)
                .where(
                    SightingReport.mobile_user_id == user_id,
                    SightingReport.is_deleted.is_(False),
                )
            )
        ).scalar_one()

    async def get_database_health(self) -> bool:
        return await check_database_health(self.db)

    async def get_redis_health(self) -> bool | None:
        if self.redis:
            return await check_redis_health(self.redis)
        return None

    async def get_user_stats(self, user_id: int) -> dict[str, Any]:
        pets, missing_reports, sighting_reports = await asyncio.gather(
            self.get_user_pets_count(user_id),
            self.get_user_missing_reports_count(user_id),
            self.get_user_sighting_reports_count(user_id),
        )
        return {
            "pets": pets,
            "missing_reports": missing_reports,
            "sighting_reports": sighting_reports,
        }

    async def get_all_stats(self) -> dict[str, Any]:
        (
            mobile_users,
            admin_users,
            pets,
            missing_reports_total,
            missing_reports_by_status,
            sighting_reports,
            db_health,
            redis_health,
        ) = await asyncio.gather(
            self.get_total_mobile_users(),
            self.get_total_admin_users(),
            self.get_total_pets(),
            self.get_total_missing_reports(),
            self.get_missing_reports_by_status(),
            self.get_total_sighting_reports(),
            self.get_database_health(),
            self.get_redis_health(),
        )

        return {
            "mobile_users": mobile_users,
            "admin_users": admin_users,
            "registered_pets": pets,
            "missing_reports": {
                "total": missing_reports_total,
                "by_status": missing_reports_by_status,
            },
            "sighting_reports": sighting_reports,
            "health": {
                "database": db_health,
                "redis": redis_health,
            },
        }

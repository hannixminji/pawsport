import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db.database import async_engine
from ..core.enums import MissingReportStatus, SightingReportStatus
from ..models._rbac_table import admin_user_role
from ..models.admin_role import AdminRole
from ..models.admin_user import AdminUser
from ..models.article import Article
from ..models.missing_report import MissingReport
from ..models.mobile_user import MobileUser
from ..models.pet import Pet
from ..models.pet_allergy import PetAllergy
from ..models.pet_inventory import PetInventory
from ..models.pet_medical_condition import PetMedicalCondition
from ..models.pet_medication import PetMedication
from ..models.pet_schedule import PetSchedule
from ..models.pet_vaccination_record import PetVaccinationRecord
from ..models.sighting_report import SightingReport
from ..models.tier import Tier

LOGGER = logging.getLogger(__name__)

_ALL_REPORT_STATUSES: list[MissingReportStatus] = [
    MissingReportStatus.LOST,
    MissingReportStatus.FOUND,
    MissingReportStatus.RETURNED,
    MissingReportStatus.CASE_CLOSED,
]

_ALL_SIGHTING_REPORT_STATUSES: list[SightingReportStatus] = [
    SightingReportStatus.SIGHTED,
    SightingReportStatus.FOSTERED,
]


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return date.today()


def _days_ago(n: int) -> datetime:
    return _now() - timedelta(days=n)


def _date_in(n: int) -> date:
    return _today() + timedelta(days=n)


def _new_session() -> AsyncSession:
    return AsyncSession(async_engine, expire_on_commit=False)


@dataclass(slots=True)
class DashboardService:
    redis: Redis | None = None

    async def get_mobile_user_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(MobileUser)
                    .where(MobileUser.is_deleted.is_(False))
                )
            ).scalar_one()

            by_tier_rows = (
                await db.execute(
                    select(Tier.name, func.count(MobileUser.id).label("count"))
                    .join(Tier, Tier.id == MobileUser.tier_id)
                    .where(MobileUser.is_deleted.is_(False))
                    .group_by(Tier.name)
                    .order_by(func.count(MobileUser.id).desc())
                )
            ).all()

            new_over_time_rows = (
                await db.execute(
                    select(
                        func.date_trunc("day", MobileUser.created_at).label("day"),
                        func.count().label("count"),
                    )
                    .where(
                        MobileUser.is_deleted.is_(False),
                        MobileUser.created_at >= _days_ago(30),
                    )
                    .group_by(text("day"))
                    .order_by(text("day"))
                )
            ).all()

            last_7 = (
                await db.execute(
                    select(func.count())
                    .select_from(MobileUser)
                    .where(
                        MobileUser.is_deleted.is_(False),
                        MobileUser.last_active_at >= _days_ago(7),
                    )
                )
            ).scalar_one()

            last_30 = (
                await db.execute(
                    select(func.count())
                    .select_from(MobileUser)
                    .where(
                        MobileUser.is_deleted.is_(False),
                        MobileUser.last_active_at >= _days_ago(30),
                    )
                )
            ).scalar_one()

        return {
            "total": total,
            "by_tier": [{"tier": name, "count": count} for name, count in by_tier_rows],
            "new_last_30_days": [
                {"day": day.date().isoformat(), "count": count}
                for day, count in new_over_time_rows
            ],
            "retention": {
                "active_last_7_days": last_7,
                "active_last_30_days": last_30,
            },
        }

    async def get_pet_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(Pet)
                    .where(Pet.is_deleted.is_(False))
                )
            ).scalar_one()

            currently_missing = (
                await db.execute(
                    select(func.count())
                    .select_from(Pet)
                    .where(Pet.is_deleted.is_(False), Pet.is_missing.is_(True))
                )
            ).scalar_one()

            by_species_rows = (
                await db.execute(
                    select(Pet.species, func.count().label("count"))
                    .where(Pet.is_deleted.is_(False))
                    .group_by(Pet.species)
                    .order_by(func.count().desc())
                )
            ).all()

            by_sex_rows = (
                await db.execute(
                    select(Pet.sex, func.count().label("count"))
                    .where(Pet.is_deleted.is_(False))
                    .group_by(Pet.sex)
                )
            ).all()

            sterilization_rows = (
                await db.execute(
                    select(Pet.is_sterilized, func.count().label("count"))
                    .where(Pet.is_deleted.is_(False))
                    .group_by(Pet.is_sterilized)
                )
            ).all()

        sterilization = {True: 0, False: 0}
        for is_sterilized, count in sterilization_rows:
            sterilization[is_sterilized] = count

        return {
            "total": total,
            "currently_missing": currently_missing,
            "by_species": [{"species": s.value, "count": c} for s, c in by_species_rows],
            "by_sex": [{"sex": s.value, "count": c} for s, c in by_sex_rows],
            "sterilized": sterilization[True],
            "not_sterilized": sterilization[False],
        }

    async def get_pet_detail_stats(self, pet_id: int) -> dict[str, Any]:
        now = _now()
        today = _today()
        in_30 = _date_in(30)

        async with _new_session() as db:
            vaccination_total = (
                await db.execute(
                    select(func.count())
                    .select_from(PetVaccinationRecord)
                    .where(
                        PetVaccinationRecord.pet_id == pet_id,
                        PetVaccinationRecord.is_deleted.is_(False),
                    )
                )
            ).scalar_one()

            vaccination_upcoming = (
                await db.execute(
                    select(func.count())
                    .select_from(PetVaccinationRecord)
                    .where(
                        PetVaccinationRecord.pet_id == pet_id,
                        PetVaccinationRecord.is_deleted.is_(False),
                        PetVaccinationRecord.next_due_date.between(today, in_30),
                    )
                )
            ).scalar_one()

            allergy_rows = (
                await db.execute(
                    select(PetAllergy.severity, func.count().label("count"))
                    .where(
                        PetAllergy.pet_id == pet_id,
                        PetAllergy.is_deleted.is_(False),
                    )
                    .group_by(PetAllergy.severity)
                )
            ).all()

            medication_rows = (
                await db.execute(
                    select(PetMedication.medication_status, func.count().label("count"))
                    .where(
                        PetMedication.pet_id == pet_id,
                        PetMedication.is_deleted.is_(False),
                    )
                    .group_by(PetMedication.medication_status)
                )
            ).all()

            condition_rows = (
                await db.execute(
                    select(
                        PetMedicalCondition.severity,
                        PetMedicalCondition.condition_status,
                        func.count().label("count"),
                    )
                    .where(
                        PetMedicalCondition.pet_id == pet_id,
                        PetMedicalCondition.is_deleted.is_(False),
                    )
                    .group_by(PetMedicalCondition.severity, PetMedicalCondition.condition_status)
                )
            ).all()

            schedule_total = (
                await db.execute(
                    select(func.count())
                    .select_from(PetSchedule)
                    .where(
                        PetSchedule.pet_id == pet_id,
                        PetSchedule.is_deleted.is_(False),
                    )
                )
            ).scalar_one()

            schedule_overdue = (
                await db.execute(
                    select(func.count())
                    .select_from(PetSchedule)
                    .where(
                        PetSchedule.pet_id == pet_id,
                        PetSchedule.is_deleted.is_(False),
                        PetSchedule.scheduled_at < now,
                    )
                )
            ).scalar_one()

            schedule_upcoming_rows = (
                await db.execute(
                    select(PetSchedule.schedule_type, func.count().label("count"))
                    .where(
                        PetSchedule.pet_id == pet_id,
                        PetSchedule.is_deleted.is_(False),
                        PetSchedule.scheduled_at >= now,
                    )
                    .group_by(PetSchedule.schedule_type)
                    .order_by(func.count().desc())
                )
            ).all()

            schedule_recurring = (
                await db.execute(
                    select(func.count())
                    .select_from(PetSchedule)
                    .where(
                        PetSchedule.pet_id == pet_id,
                        PetSchedule.is_deleted.is_(False),
                        PetSchedule.is_recurring.is_(True),
                    )
                )
            ).scalar_one()

            missing_report_rows = (
                await db.execute(
                    select(MissingReport.report_status, func.count().label("count"))
                    .where(
                        MissingReport.pet_id == pet_id,
                        MissingReport.is_deleted.is_(False),
                    )
                    .group_by(MissingReport.report_status)
                )
            ).all()

        allergy_by_severity = {s.value: c for s, c in allergy_rows}
        medication_by_status = {s.value: c for s, c in medication_rows}

        condition_by_severity: dict[str, int] = {}
        condition_by_status: dict[str, int] = {}
        for severity, condition_status, count in condition_rows:
            condition_by_severity[severity.value] = condition_by_severity.get(severity.value, 0) + count
            condition_by_status[condition_status.value] = condition_by_status.get(condition_status.value, 0) + count

        missing_by_status = {s.value: 0 for s in _ALL_REPORT_STATUSES}
        for status, count in missing_report_rows:
            missing_by_status[status.value] = count

        return {
            "vaccinations": {
                "total": vaccination_total,
                "upcoming_due_within_30_days": vaccination_upcoming,
            },
            "allergies": {
                "total": sum(allergy_by_severity.values()),
                "by_severity": allergy_by_severity,
            },
            "medications": {
                "total": sum(medication_by_status.values()),
                "by_status": medication_by_status,
            },
            "medical_conditions": {
                "total": sum(condition_by_severity.values()),
                "by_severity": condition_by_severity,
                "by_status": condition_by_status,
            },
            "schedules": {
                "total": schedule_total,
                "overdue": schedule_overdue,
                "recurring": schedule_recurring,
                "upcoming_by_type": [
                    {"schedule_type": t.value, "count": c}
                    for t, c in schedule_upcoming_rows
                ],
            },
            "missing_reports": {
                "total": sum(missing_by_status.values()),
                "by_status": missing_by_status,
            },
        }

    async def get_missing_report_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(MissingReport)
                    .where(MissingReport.is_deleted.is_(False))
                )
            ).scalar_one()

            by_status_rows = (
                await db.execute(
                    select(MissingReport.report_status, func.count().label("count"))
                    .where(MissingReport.is_deleted.is_(False))
                    .group_by(MissingReport.report_status)
                )
            ).all()

            active_lost = (
                await db.execute(
                    select(func.count())
                    .select_from(MissingReport)
                    .where(
                        MissingReport.is_deleted.is_(False),
                        MissingReport.report_status == MissingReportStatus.LOST,
                    )
                )
            ).scalar_one()

            over_time_rows = (
                await db.execute(
                    select(
                        func.date_trunc("day", MissingReport.created_at).label("day"),
                        func.count().label("count"),
                    )
                    .where(
                        MissingReport.is_deleted.is_(False),
                        MissingReport.created_at >= _days_ago(30),
                    )
                    .group_by(text("day"))
                    .order_by(text("day"))
                )
            ).all()

        by_status = {s.value: 0 for s in _ALL_REPORT_STATUSES}
        for status, count in by_status_rows:
            by_status[status.value] = count

        return {
            "total": total,
            "active_lost": active_lost,
            "by_status": by_status,
            "opened_last_30_days": [
                {"day": day.date().isoformat(), "count": count}
                for day, count in over_time_rows
            ],
        }

    async def get_sighting_report_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(SightingReport)
                    .where(SightingReport.is_deleted.is_(False))
                )
            ).scalar_one()

            by_species_rows = (
                await db.execute(
                    select(SightingReport.pet_species, func.count().label("count"))
                    .where(SightingReport.is_deleted.is_(False))
                    .group_by(SightingReport.pet_species)
                    .order_by(func.count().desc())
                )
            ).all()

            auth_vs_guest_rows = (
                await db.execute(
                    select(
                        case(
                            (SightingReport.mobile_user_id.is_(None), "guest"),
                            else_="authenticated",
                        ).label("type"),
                        func.count().label("count"),
                    )
                    .where(SightingReport.is_deleted.is_(False))
                    .group_by(text("type"))
                )
            ).all()

            by_status_rows = (
                await db.execute(
                    select(SightingReport.status, func.count().label("count"))
                    .where(SightingReport.is_deleted.is_(False))
                    .group_by(SightingReport.status)
                )
            ).all()

        auth_vs_guest = {"authenticated": 0, "guest": 0}
        for type_, count in auth_vs_guest_rows:
            auth_vs_guest[type_] = count

        by_status = {s.value: 0 for s in _ALL_SIGHTING_REPORT_STATUSES}
        for status, count in by_status_rows:
            by_status[status.value] = count

        return {
            "total": total,
            "by_species": [{"species": s.value, "count": c} for s, c in by_species_rows],
            "by_status": by_status,
            **auth_vs_guest,
        }

    async def get_pet_health_stats(self) -> dict[str, Any]:
        today = _today()
        in_30 = _date_in(30)

        async with _new_session() as db:
            vaccination_total = (
                await db.execute(
                    select(func.count())
                    .select_from(PetVaccinationRecord)
                    .where(PetVaccinationRecord.is_deleted.is_(False))
                )
            ).scalar_one()

            vaccination_upcoming = (
                await db.execute(
                    select(func.count())
                    .select_from(PetVaccinationRecord)
                    .where(
                        PetVaccinationRecord.is_deleted.is_(False),
                        PetVaccinationRecord.next_due_date.between(today, in_30),
                    )
                )
            ).scalar_one()

            allergy_rows = (
                await db.execute(
                    select(PetAllergy.severity, func.count().label("count"))
                    .where(PetAllergy.is_deleted.is_(False))
                    .group_by(PetAllergy.severity)
                )
            ).all()

            medication_rows = (
                await db.execute(
                    select(PetMedication.medication_status, func.count().label("count"))
                    .where(PetMedication.is_deleted.is_(False))
                    .group_by(PetMedication.medication_status)
                )
            ).all()

            condition_rows = (
                await db.execute(
                    select(
                        PetMedicalCondition.severity,
                        PetMedicalCondition.condition_status,
                        func.count().label("count"),
                    )
                    .where(PetMedicalCondition.is_deleted.is_(False))
                    .group_by(PetMedicalCondition.severity, PetMedicalCondition.condition_status)
                )
            ).all()

        allergy_by_severity = {s.value: c for s, c in allergy_rows}
        medication_by_status = {s.value: c for s, c in medication_rows}

        condition_by_severity: dict[str, int] = {}
        condition_by_status: dict[str, int] = {}
        total_conditions = 0
        for severity, condition_status, count in condition_rows:
            condition_by_severity[severity.value] = condition_by_severity.get(severity.value, 0) + count
            condition_by_status[condition_status.value] = condition_by_status.get(condition_status.value, 0) + count
            total_conditions += count

        return {
            "vaccinations": {
                "total": vaccination_total,
                "upcoming_due_within_30_days": vaccination_upcoming,
            },
            "allergies": {
                "total": sum(allergy_by_severity.values()),
                "by_severity": allergy_by_severity,
            },
            "medications": {
                "total": sum(medication_by_status.values()),
                "by_status": medication_by_status,
            },
            "medical_conditions": {
                "total": total_conditions,
                "by_severity": condition_by_severity,
                "by_status": condition_by_status,
            },
        }

    async def get_pet_schedule_stats(self) -> dict[str, Any]:
        now = _now()

        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(PetSchedule)
                    .where(PetSchedule.is_deleted.is_(False))
                )
            ).scalar_one()

            upcoming_by_type_rows = (
                await db.execute(
                    select(PetSchedule.schedule_type, func.count().label("count"))
                    .where(
                        PetSchedule.is_deleted.is_(False),
                        PetSchedule.scheduled_at >= now,
                    )
                    .group_by(PetSchedule.schedule_type)
                    .order_by(func.count().desc())
                )
            ).all()

            overdue = (
                await db.execute(
                    select(func.count())
                    .select_from(PetSchedule)
                    .where(
                        PetSchedule.is_deleted.is_(False),
                        PetSchedule.scheduled_at < now,
                    )
                )
            ).scalar_one()

        return {
            "total": total,
            "overdue": overdue,
            "upcoming_by_type": [
                {"schedule_type": t.value, "count": c}
                for t, c in upcoming_by_type_rows
            ],
        }

    async def get_pet_inventory_stats(self) -> dict[str, Any]:
        today = _today()
        in_30 = _date_in(30)

        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(PetInventory)
                    .where(PetInventory.is_deleted.is_(False))
                )
            ).scalar_one()

            by_type_rows = (
                await db.execute(
                    select(PetInventory.inventory_type, func.count().label("count"))
                    .where(PetInventory.is_deleted.is_(False))
                    .group_by(PetInventory.inventory_type)
                    .order_by(func.count().desc())
                )
            ).all()

            expiring_soon = (
                await db.execute(
                    select(func.count())
                    .select_from(PetInventory)
                    .where(
                        PetInventory.is_deleted.is_(False),
                        PetInventory.expiration_date.between(today, in_30),
                    )
                )
            ).scalar_one()

        return {
            "total": total,
            "expiring_within_30_days": expiring_soon,
            "by_type": [
                {"inventory_type": t.value, "count": c}
                for t, c in by_type_rows
            ],
        }

    async def get_article_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(Article)
                    .where(Article.is_deleted.is_(False))
                )
            ).scalar_one()

            by_category_rows = (
                await db.execute(
                    select(Article.category, func.count().label("count"))
                    .where(Article.is_deleted.is_(False))
                    .group_by(Article.category)
                    .order_by(func.count().desc())
                )
            ).all()

        return {
            "total": total,
            "by_category": [
                {"category": cat.value if cat else None, "count": count}
                for cat, count in by_category_rows
            ],
        }

    async def get_admin_user_stats(self) -> dict[str, Any]:
        async with _new_session() as db:
            total = (
                await db.execute(
                    select(func.count())
                    .select_from(AdminUser)
                    .where(AdminUser.is_deleted.is_(False))
                )
            ).scalar_one()

            by_status_rows = (
                await db.execute(
                    select(AdminUser.account_status, func.count().label("count"))
                    .where(AdminUser.is_deleted.is_(False))
                    .group_by(AdminUser.account_status)
                )
            ).all()

            by_role_rows = (
                await db.execute(
                    select(AdminRole.name, func.count(admin_user_role.c.admin_user_id).label("count"))
                    .join(admin_user_role, admin_user_role.c.admin_role_id == AdminRole.id)
                    .group_by(AdminRole.name)
                    .order_by(func.count(admin_user_role.c.admin_user_id).desc())
                )
            ).all()

            recently_active_rows = (
                await db.execute(
                    select(AdminUser.id, AdminUser.username, AdminUser.last_active_at)
                    .where(
                        AdminUser.is_deleted.is_(False),
                        AdminUser.last_active_at >= _days_ago(7),
                    )
                    .order_by(AdminUser.last_active_at.desc())
                    .limit(10)
                )
            ).all()

        return {
            "total": total,
            "by_status": [{"status": s.value, "count": c} for s, c in by_status_rows],
            "by_role": [{"role": name, "count": count} for name, count in by_role_rows],
            "recently_active": [
                {
                    "id": id_,
                    "username": username,
                    "last_active_at": last_active_at.isoformat() if last_active_at else None,
                }
                for id_, username, last_active_at in recently_active_rows
            ],
        }

    async def get_tier_stats(self) -> list[dict[str, Any]]:
        async with _new_session() as db:
            rows = (
                await db.execute(
                    select(Tier.name, func.count(MobileUser.id).label("count"))
                    .outerjoin(
                        MobileUser,
                        (MobileUser.tier_id == Tier.id) & MobileUser.is_deleted.is_(False),
                    )
                    .group_by(Tier.name)
                    .order_by(func.count(MobileUser.id).desc())
                )
            ).all()

        return [{"tier": name, "users": count} for name, count in rows]

    async def get_health(self) -> dict[str, Any]:
        db_health: bool
        redis_health: bool | None = None

        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_health = True
        except Exception as e:
            LOGGER.exception(f"Database health check failed with error: {e}")
            db_health = False

        if self.redis:
            try:
                await self.redis.ping()
                redis_health = True
            except Exception as e:
                LOGGER.exception(f"Redis health check failed with error: {e}")
                redis_health = False

        return {"database": db_health, "redis": redis_health}

    async def get_user_stats(self, user_id: int) -> dict[str, Any]:
        async with _new_session() as db:
            pets = (
                await db.execute(
                    select(func.count())
                    .select_from(Pet)
                    .where(Pet.owner_id == user_id, Pet.is_deleted.is_(False))
                )
            ).scalar_one()

            missing_reports = (
                await db.execute(
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

            sighting_reports = (
                await db.execute(
                    select(func.count())
                    .select_from(SightingReport)
                    .where(
                        SightingReport.mobile_user_id == user_id,
                        SightingReport.is_deleted.is_(False),
                    )
                )
            ).scalar_one()

        return {
            "pets": pets,
            "missing_reports": missing_reports,
            "sighting_reports": sighting_reports,
        }

    async def get_all_stats(self) -> dict[str, Any]:
        (
            mobile_users,
            pets,
            missing_reports,
            sighting_reports,
            pet_health,
            pet_schedules,
            pet_inventory,
            articles,
            admin_users,
            tiers,
            health,
        ) = await asyncio.gather(
            self.get_mobile_user_stats(),
            self.get_pet_stats(),
            self.get_missing_report_stats(),
            self.get_sighting_report_stats(),
            self.get_pet_health_stats(),
            self.get_pet_schedule_stats(),
            self.get_pet_inventory_stats(),
            self.get_article_stats(),
            self.get_admin_user_stats(),
            self.get_tier_stats(),
            self.get_health(),
        )
        return {
            "mobile_users": mobile_users,
            "pets": pets,
            "missing_reports": missing_reports,
            "sighting_reports": sighting_reports,
            "pet_health": pet_health,
            "pet_schedules": pet_schedules,
            "pet_inventory": pet_inventory,
            "articles": articles,
            "admin_users": admin_users,
            "tiers": tiers,
            "health": health,
        }

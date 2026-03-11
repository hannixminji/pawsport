import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import MissingReportStatus, SightingReportStatus
from ..core.health import check_database_health, check_redis_health
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


@dataclass(slots=True)
class DashboardService:
    db: AsyncSession
    redis: Redis | None = None

    async def _mobile_users_total(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(MobileUser)
                .where(MobileUser.is_deleted.is_(False))
            )
        ).scalar_one()

    async def _mobile_users_by_tier(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Tier.name, func.count(MobileUser.id).label("count"))
                .join(Tier, Tier.id == MobileUser.tier_id)
                .where(MobileUser.is_deleted.is_(False))
                .group_by(Tier.name)
                .order_by(func.count(MobileUser.id).desc())
            )
        ).all()
        return [{"tier": name, "count": count} for name, count in rows]

    async def _mobile_users_new_over_time(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
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
        return [{"day": day.date().isoformat(), "count": count} for day, count in rows]

    async def _mobile_users_retention(self) -> dict[str, int]:
        base = (
            select(func.count())
            .select_from(MobileUser)
            .where(MobileUser.is_deleted.is_(False))
        )
        last_7, last_30 = await asyncio.gather(
            self.db.execute(base.where(MobileUser.last_active_at >= _days_ago(7))),
            self.db.execute(base.where(MobileUser.last_active_at >= _days_ago(30))),
        )
        return {
            "active_last_7_days": last_7.scalar_one(),
            "active_last_30_days": last_30.scalar_one(),
        }

    async def get_mobile_user_stats(self) -> dict[str, Any]:
        total, by_tier, new_over_time, retention = await asyncio.gather(
            self._mobile_users_total(),
            self._mobile_users_by_tier(),
            self._mobile_users_new_over_time(),
            self._mobile_users_retention(),
        )
        return {
            "total": total,
            "by_tier": by_tier,
            "new_last_30_days": new_over_time,
            "retention": retention,
        }

    async def _pets_by_species(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Pet.species, func.count().label("count"))
                .where(Pet.is_deleted.is_(False))
                .group_by(Pet.species)
                .order_by(func.count().desc())
            )
        ).all()
        return [{"species": species.value, "count": count} for species, count in rows]

    async def _pets_by_sex(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Pet.sex, func.count().label("count"))
                .where(Pet.is_deleted.is_(False))
                .group_by(Pet.sex)
            )
        ).all()
        return [{"sex": sex.value, "count": count} for sex, count in rows]

    async def _pets_sterilization(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(Pet.is_sterilized, func.count().label("count"))
                .where(Pet.is_deleted.is_(False))
                .group_by(Pet.is_sterilized)
            )
        ).all()
        result = {True: 0, False: 0}
        for is_sterilized, count in rows:
            result[is_sterilized] = count
        return {"sterilized": result[True], "not_sterilized": result[False]}

    async def get_pet_stats(self) -> dict[str, Any]:
        total, currently_missing, by_species, by_sex, sterilization = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(Pet)
                .where(Pet.is_deleted.is_(False))
            ),
            self.db.execute(
                select(func.count())
                .select_from(Pet)
                .where(Pet.is_deleted.is_(False), Pet.is_missing.is_(True))
            ),
            self._pets_by_species(),
            self._pets_by_sex(),
            self._pets_sterilization(),
        )
        return {
            "total": total.scalar_one(),
            "currently_missing": currently_missing.scalar_one(),
            "by_species": by_species,
            "by_sex": by_sex,
            **sterilization,
        }

    async def get_pet_detail_stats(self, pet_id: int) -> dict[str, Any]:
        now = _now()
        today = _today()
        in_30 = _date_in(30)

        (
            vaccination_total,
            vaccination_upcoming,
            allergy_rows,
            medication_rows,
            condition_rows,
            schedule_total,
            schedule_overdue,
            schedule_upcoming_rows,
            schedule_recurring,
            missing_report_rows,
        ) = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(PetVaccinationRecord)
                .where(
                    PetVaccinationRecord.pet_id == pet_id,
                    PetVaccinationRecord.is_deleted.is_(False),
                )
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetVaccinationRecord)
                .where(
                    PetVaccinationRecord.pet_id == pet_id,
                    PetVaccinationRecord.is_deleted.is_(False),
                    PetVaccinationRecord.next_due_date.between(today, in_30),
                )
            ),
            self.db.execute(
                select(PetAllergy.severity, func.count().label("count"))
                .where(
                    PetAllergy.pet_id == pet_id,
                    PetAllergy.is_deleted.is_(False),
                )
                .group_by(PetAllergy.severity)
            ),
            self.db.execute(
                select(PetMedication.medication_status, func.count().label("count"))
                .where(
                    PetMedication.pet_id == pet_id,
                    PetMedication.is_deleted.is_(False),
                )
                .group_by(PetMedication.medication_status)
            ),
            self.db.execute(
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
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetSchedule)
                .where(
                    PetSchedule.pet_id == pet_id,
                    PetSchedule.is_deleted.is_(False),
                )
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetSchedule)
                .where(
                    PetSchedule.pet_id == pet_id,
                    PetSchedule.is_deleted.is_(False),
                    PetSchedule.scheduled_at < now,
                )
            ),
            self.db.execute(
                select(PetSchedule.schedule_type, func.count().label("count"))
                .where(
                    PetSchedule.pet_id == pet_id,
                    PetSchedule.is_deleted.is_(False),
                    PetSchedule.scheduled_at >= now,
                )
                .group_by(PetSchedule.schedule_type)
                .order_by(func.count().desc())
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetSchedule)
                .where(
                    PetSchedule.pet_id == pet_id,
                    PetSchedule.is_deleted.is_(False),
                    PetSchedule.is_recurring.is_(True),
                )
            ),
            self.db.execute(
                select(MissingReport.report_status, func.count().label("count"))
                .where(
                    MissingReport.pet_id == pet_id,
                    MissingReport.is_deleted.is_(False),
                )
                .group_by(MissingReport.report_status)
            ),
        )

        allergy_by_severity = {s.value: c for s, c in allergy_rows.all()}
        medication_by_status = {s.value: c for s, c in medication_rows.all()}

        condition_by_severity: dict[str, int] = {}
        condition_by_status: dict[str, int] = {}
        for severity, condition_status, count in condition_rows.all():
            condition_by_severity[severity.value] = condition_by_severity.get(severity.value, 0) + count
            condition_by_status[condition_status.value] = condition_by_status.get(condition_status.value, 0) + count

        missing_by_status = {s.value: 0 for s in _ALL_REPORT_STATUSES}
        for status, count in missing_report_rows.all():
            missing_by_status[status.value] = count

        return {
            "vaccinations": {
                "total": vaccination_total.scalar_one(),
                "upcoming_due_within_30_days": vaccination_upcoming.scalar_one(),
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
                "total": schedule_total.scalar_one(),
                "overdue": schedule_overdue.scalar_one(),
                "recurring": schedule_recurring.scalar_one(),
                "upcoming_by_type": [
                    {"schedule_type": t.value, "count": c}
                    for t, c in schedule_upcoming_rows.all()
                ],
            },
            "missing_reports": {
                "total": sum(missing_by_status.values()),
                "by_status": missing_by_status,
            },
        }

    async def _missing_reports_by_status(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(MissingReport.report_status, func.count().label("count"))
                .where(MissingReport.is_deleted.is_(False))
                .group_by(MissingReport.report_status)
            )
        ).all()
        result = {s.value: 0 for s in _ALL_REPORT_STATUSES}
        for status, count in rows:
            result[status.value] = count
        return result

    async def _missing_reports_over_time(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
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
        return [{"day": day.date().isoformat(), "count": count} for day, count in rows]

    async def get_missing_report_stats(self) -> dict[str, Any]:
        total, by_status, active_lost, over_time = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(MissingReport)
                .where(MissingReport.is_deleted.is_(False))
            ),
            self._missing_reports_by_status(),
            self.db.execute(
                select(func.count())
                .select_from(MissingReport)
                .where(
                    MissingReport.is_deleted.is_(False),
                    MissingReport.report_status == MissingReportStatus.LOST,
                )
            ),
            self._missing_reports_over_time(),
        )
        return {
            "total": total.scalar_one(),
            "active_lost": active_lost.scalar_one(),
            "by_status": by_status,
            "opened_last_30_days": over_time,
        }

    async def _sighting_reports_by_species(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(SightingReport.pet_species, func.count().label("count"))
                .where(SightingReport.is_deleted.is_(False))
                .group_by(SightingReport.pet_species)
                .order_by(func.count().desc())
            )
        ).all()
        return [{"species": species.value, "count": count} for species, count in rows]

    async def _sighting_reports_auth_vs_guest(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
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
        result = {"authenticated": 0, "guest": 0}
        for type_, count in rows:
            result[type_] = count
        return result

    async def _sighting_reports_by_status(self) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(SightingReport.status, func.count().label("count"))
                .where(SightingReport.is_deleted.is_(False))
                .group_by(SightingReport.status)
            )
        ).all()
        result = {s.value: 0 for s in _ALL_SIGHTING_REPORT_STATUSES}
        for status, count in rows:
            result[status.value] = count
        return result

    async def get_sighting_report_stats(self) -> dict[str, Any]:
        total, by_species, auth_vs_guest, by_status = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(SightingReport)
                .where(SightingReport.is_deleted.is_(False))
            ),
            self._sighting_reports_by_species(),
            self._sighting_reports_auth_vs_guest(),
            self._sighting_reports_by_status(),
        )
        return {
            "total": total.scalar_one(),
            "by_species": by_species,
            "by_status": by_status,
            **auth_vs_guest,
        }

    async def _vaccination_stats(self) -> dict[str, Any]:
        today = _today()
        in_30 = _date_in(30)

        total, upcoming = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(PetVaccinationRecord)
                .where(PetVaccinationRecord.is_deleted.is_(False))
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetVaccinationRecord)
                .where(
                    PetVaccinationRecord.is_deleted.is_(False),
                    PetVaccinationRecord.next_due_date.between(today, in_30),
                )
            ),
        )
        return {
            "total": total.scalar_one(),
            "upcoming_due_within_30_days": upcoming.scalar_one(),
        }

    async def _allergy_stats(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                select(PetAllergy.severity, func.count().label("count"))
                .where(PetAllergy.is_deleted.is_(False))
                .group_by(PetAllergy.severity)
            )
        ).all()
        by_severity = {severity.value: count for severity, count in rows}
        return {
            "total": sum(by_severity.values()),
            "by_severity": by_severity,
        }

    async def _medication_stats(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                select(PetMedication.medication_status, func.count().label("count"))
                .where(PetMedication.is_deleted.is_(False))
                .group_by(PetMedication.medication_status)
            )
        ).all()
        by_status = {status.value: count for status, count in rows}
        return {
            "total": sum(by_status.values()),
            "by_status": by_status,
        }

    async def _medical_condition_stats(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                select(
                    PetMedicalCondition.severity,
                    PetMedicalCondition.condition_status,
                    func.count().label("count"),
                )
                .where(PetMedicalCondition.is_deleted.is_(False))
                .group_by(PetMedicalCondition.severity, PetMedicalCondition.condition_status)
            )
        ).all()
        by_severity: dict[str, int] = {}
        by_status: dict[str, int] = {}
        total = 0
        for severity, condition_status, count in rows:
            by_severity[severity.value] = by_severity.get(severity.value, 0) + count
            by_status[condition_status.value] = by_status.get(condition_status.value, 0) + count
            total += count
        return {
            "total": total,
            "by_severity": by_severity,
            "by_status": by_status,
        }

    async def get_pet_health_stats(self) -> dict[str, Any]:
        vaccinations, allergies, medications, conditions = await asyncio.gather(
            self._vaccination_stats(),
            self._allergy_stats(),
            self._medication_stats(),
            self._medical_condition_stats(),
        )
        return {
            "vaccinations": vaccinations,
            "allergies": allergies,
            "medications": medications,
            "medical_conditions": conditions,
        }

    async def get_pet_schedule_stats(self) -> dict[str, Any]:
        now = _now()

        total, upcoming_by_type, overdue = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(PetSchedule)
                .where(PetSchedule.is_deleted.is_(False))
            ),
            self.db.execute(
                select(PetSchedule.schedule_type, func.count().label("count"))
                .where(
                    PetSchedule.is_deleted.is_(False),
                    PetSchedule.scheduled_at >= now,
                )
                .group_by(PetSchedule.schedule_type)
                .order_by(func.count().desc())
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetSchedule)
                .where(
                    PetSchedule.is_deleted.is_(False),
                    PetSchedule.scheduled_at < now,
                )
            ),
        )
        return {
            "total": total.scalar_one(),
            "overdue": overdue.scalar_one(),
            "upcoming_by_type": [
                {"schedule_type": t.value, "count": c}
                for t, c in upcoming_by_type.all()
            ],
        }

    async def get_pet_inventory_stats(self) -> dict[str, Any]:
        today = _today()
        in_30 = _date_in(30)

        total, by_type, expiring_soon = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(PetInventory)
                .where(PetInventory.is_deleted.is_(False))
            ),
            self.db.execute(
                select(PetInventory.inventory_type, func.count().label("count"))
                .where(PetInventory.is_deleted.is_(False))
                .group_by(PetInventory.inventory_type)
                .order_by(func.count().desc())
            ),
            self.db.execute(
                select(func.count())
                .select_from(PetInventory)
                .where(
                    PetInventory.is_deleted.is_(False),
                    PetInventory.expiration_date.between(today, in_30),
                )
            ),
        )
        return {
            "total": total.scalar_one(),
            "expiring_within_30_days": expiring_soon.scalar_one(),
            "by_type": [
                {"inventory_type": t.value, "count": c}
                for t, c in by_type.all()
            ],
        }

    async def get_article_stats(self) -> dict[str, Any]:
        total, by_category = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(Article)
                .where(Article.is_deleted.is_(False))
            ),
            self.db.execute(
                select(Article.category, func.count().label("count"))
                .where(Article.is_deleted.is_(False))
                .group_by(Article.category)
                .order_by(func.count().desc())
            ),
        )
        return {
            "total": total.scalar_one(),
            "by_category": [
                {"category": cat.value if cat else None, "count": count}
                for cat, count in by_category.all()
            ],
        }

    async def _admin_users_by_status(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(AdminUser.account_status, func.count().label("count"))
                .where(AdminUser.is_deleted.is_(False))
                .group_by(AdminUser.account_status)
            )
        ).all()
        return [{"status": status.value, "count": count} for status, count in rows]

    async def _admin_users_by_role(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(AdminRole.name, func.count(admin_user_role.c.admin_user_id).label("count"))
                .join(admin_user_role, admin_user_role.c.admin_role_id == AdminRole.id)
                .group_by(AdminRole.name)
                .order_by(func.count(admin_user_role.c.admin_user_id).desc())
            )
        ).all()
        return [{"role": name, "count": count} for name, count in rows]

    async def _admin_users_recently_active(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(AdminUser.id, AdminUser.username, AdminUser.last_active_at)
                .where(
                    AdminUser.is_deleted.is_(False),
                    AdminUser.last_active_at >= _days_ago(7),
                )
                .order_by(AdminUser.last_active_at.desc())
                .limit(10)
            )
        ).all()
        return [
            {
                "id": id_,
                "username": username,
                "last_active_at": last_active_at.isoformat() if last_active_at else None,
            }
            for id_, username, last_active_at in rows
        ]

    async def get_admin_user_stats(self) -> dict[str, Any]:
        total, by_status, by_role, recently_active = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(AdminUser)
                .where(AdminUser.is_deleted.is_(False))
            ),
            self._admin_users_by_status(),
            self._admin_users_by_role(),
            self._admin_users_recently_active(),
        )
        return {
            "total": total.scalar_one(),
            "by_status": by_status,
            "by_role": by_role,
            "recently_active": recently_active,
        }

    async def get_tier_stats(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
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
        db_health, redis_health = await asyncio.gather(
            check_database_health(self.db),
            check_redis_health(self.redis) if self.redis else asyncio.sleep(0, result=None),
        )
        return {"database": db_health, "redis": redis_health}

    async def get_user_stats(self, user_id: int) -> dict[str, Any]:
        pets, missing_reports, sighting_reports = await asyncio.gather(
            self.db.execute(
                select(func.count())
                .select_from(Pet)
                .where(Pet.owner_id == user_id, Pet.is_deleted.is_(False))
            ),
            self.db.execute(
                select(func.count())
                .select_from(MissingReport)
                .join(Pet, MissingReport.pet_id == Pet.id)
                .where(
                    Pet.owner_id == user_id,
                    MissingReport.is_deleted.is_(False),
                    Pet.is_deleted.is_(False),
                )
            ),
            self.db.execute(
                select(func.count())
                .select_from(SightingReport)
                .where(
                    SightingReport.mobile_user_id == user_id,
                    SightingReport.is_deleted.is_(False),
                )
            ),
        )
        return {
            "pets": pets.scalar_one(),
            "missing_reports": missing_reports.scalar_one(),
            "sighting_reports": sighting_reports.scalar_one(),
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

import logging
from dataclasses import dataclass

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.enums import ActorType, MissingReportStatus
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils import queue
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.missing_report import MissingReport
from ..models.pet import Pet
from ..models.pet_photo import PetPhoto
from ..schemas.missing_report import MissingReportCreate, MissingReportRead, MissingReportUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MissingReportService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "pet_id",
        "last_seen_location",
        "description",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "last_seen_location",
        "description",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "pet_id": frozenset({
            FilterOp.EQ,
        }),
        "last_seen_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "last_seen_address": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "report_status": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS = {
        "last_seen_at",
        "created_at",
    }

    def _is_unique_constraint_violation(self, error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_pet(self, pet_id: int, actor: Actor | None = None) -> Pet | None:
        query = (
            select(Pet)
            .where(
                Pet.id == pet_id,
                Pet.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(Pet.owner_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _get_pet_photo_uuids_by_pet_id(self, pet_id: int) -> list[str]:
        uuids = (
            await self.db.execute(
                select(PetPhoto.uuid)
                .where(
                    PetPhoto.pet_id == pet_id,
                    PetPhoto.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        return [str(uuid) for uuid in uuids]

    async def _get_missing_report(
        self,
        missing_report_id: int,
        actor: Actor | None = None,
        with_photos: bool = False,
    ) -> MissingReport | None:
        query = select(MissingReport)

        if with_photos:
            query = query.options(selectinload(MissingReport.pet).selectinload(Pet.photos))

        query = (
            query
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                MissingReport.id == missing_report_id,
                MissingReport.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(Pet.owner_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _update_pet_missing_status(
        self,
        pet_id: int,
        is_missing: bool,
    ) -> None:
        await self.db.execute(
            update(Pet)
            .where(Pet.id == pet_id)
            .values(is_missing=is_missing)
        )

    async def _enqueue_nearby_users_notification(
        self,
        *,
        actor: Actor,
        pet_id: int,
        report_id: int,
        pet_label: str,
        longitude: float,
        latitude: float,
    ) -> None:
        await queue.pool.enqueue_job(
            "notify_nearby_alert_center_task",
            event_longitude=longitude,
            event_latitude=latitude,
            notification_title="🚨 Missing pet alert",
            notification_body=f"A missing {pet_label} was reported nearby. Tap to view details.",
            notification_data={
                "type": "missing_report_created",
                "pet_id": str(pet_id),
                "missing_report_id": str(report_id),
                "pet_type": pet_label,
                "username": actor.username,
            },
            notification_feature="nearby_report_alerts",
            radius_in_meters=settings.NEARBY_ALERT_CENTER_RADIUS_METERS,
            excluded_user_id=actor.id,
        )

    async def create(
        self,
        *,
        actor: Actor,
        pet_id: int,
        report_input: MissingReportCreate,
    ) -> MissingReportRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to create a missing report.")

        db_pet = await self._get_pet(pet_id, actor)
        if db_pet is None:
            raise NotFoundError("Pet not found.")

        pet_type = db_pet.species.value.lower().strip()
        if pet_type not in {"dog", "cat"}:
            raise InvalidInputError("Missing reports are only supported for dogs and cats.")
        pet_label = pet_type

        wkb_location = from_shape(
            Point(
                report_input.last_seen_location.longitude,
                report_input.last_seen_location.latitude,
            ),
            srid=4326,
        )

        missing_report = MissingReport(
            **report_input.model_dump(exclude={"last_seen_location"}),
            pet_id=pet_id,
            last_seen_location=wkb_location,
            report_status=MissingReportStatus.LOST,
        )
        self.db.add(missing_report)

        await self._update_pet_missing_status(pet_id, True)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_missing_report_one_lost_per_pet_active"):
                raise InvalidInputError("A missing report for this pet already exists.")

            raise InvalidInputError("Unable to create the missing report.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the missing report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the missing report."
            ) from error

        await self.db.refresh(missing_report)

        pet_photo_uuids = await self._get_pet_photo_uuids_by_pet_id(pet_id)

        if pet_photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_update_payload_task",
                    collection_name="pet_photos",
                    point_ids=pet_photo_uuids,
                    payload={"is_missing": True},
                )

            except Exception as error:
                LOGGER.error(f"Failed to enqueue Qdrant payload update for missing status {missing_report.id}: {error}")

        try:
            await self._enqueue_nearby_users_notification(
                actor=actor,
                pet_id=pet_id,
                report_id=missing_report.id,
                pet_label=pet_label,
                longitude=report_input.last_seen_location.longitude,
                latitude=report_input.last_seen_location.latitude,
            )

        except Exception as e:
            LOGGER.warning(f"Failed to enqueue notify_nearby_alert_center_task: {e}")

        return MissingReportRead.model_validate(missing_report)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[MissingReportRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view missing reports.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        blacklisted = (
            self.MOBILE_SEARCH_BLACKLIST_COLUMNS
            if actor.actor_type == ActorType.MOBILE_USER
            else self.ADMIN_SEARCH_BLACKLIST_COLUMNS
        )

        if (
            actor.actor_type == ActorType.MOBILE_USER
            or (actor.actor_type == ActorType.ADMIN_USER and user_id is not None)
        ):
            base_query = (
                select(MissingReport)
                .join(Pet, Pet.id == MissingReport.pet_id)
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                    MissingReport.is_deleted.is_(False),
                )
            )
        else:
            base_query = (
                select(MissingReport)
                .join(Pet, Pet.id == MissingReport.pet_id)
                .where(
                    Pet.is_deleted.is_(False),
                    MissingReport.is_deleted.is_(False),
                )
            )

        if pet_id is not None:
            base_query = base_query.where(MissingReport.pet_id == pet_id)

        engine = SearchEngine(
            db=self.db,
            model=MissingReport,
            blacklisted_columns=blacklisted,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=MissingReportRead.model_validate,
        )

        return PaginatedResponse[MissingReportRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_missing_reports(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
        pet_id: int | None = None,
    ) -> PaginatedResponse[MissingReportRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view missing reports.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(MissingReport)
            .join(Pet, Pet.id == MissingReport.pet_id)
            .where(
                Pet.is_deleted.is_(False),
                MissingReport.is_deleted.is_(False),
            )
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        if pet_id is not None:
            base_query = base_query.where(MissingReport.pet_id == pet_id)

        db_reports = (
            await self.db.execute(
                base_query
                .options(selectinload(MissingReport.pet).selectinload(Pet.photos))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(base_query.subquery())
            )
        ).scalar_one()

        return PaginatedResponse[MissingReportRead](
            data=[MissingReportRead.model_validate(report) for report in db_reports],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_missing_report(
        self,
        *,
        actor: Actor,
        missing_report_id: int,
    ) -> MissingReportRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this missing report.")

        db_missing_report = await self._get_missing_report(missing_report_id, actor, with_photos=True)
        if db_missing_report is None:
            raise NotFoundError("Missing report not found.")

        return MissingReportRead.model_validate(db_missing_report)

    async def update(
        self,
        *,
        actor: Actor,
        missing_report_id: int,
        report_input: MissingReportUpdate,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this missing report.")

        db_missing_report = await self._get_missing_report(missing_report_id, actor)
        if db_missing_report is None:
            raise NotFoundError("Missing report not found.")

        if report_input.last_seen_location is not None:
            wkb_location = from_shape(
                Point(
                    report_input.last_seen_location.longitude,
                    report_input.last_seen_location.latitude,
                ),
                srid=4326,
            )
            db_missing_report.last_seen_location = wkb_location

        apply_partial_update(
            target=db_missing_report,
            input=report_input,
            exclude={"last_seen_location"},
        )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_missing_report_one_lost_per_pet_active"):
                raise InvalidInputError("A missing report for this pet already exists.")

            raise InvalidInputError("Unable to update the missing report.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the missing report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the missing report."
            ) from error

    async def update_status(
        self,
        *,
        actor: Actor,
        missing_report_id: int,
        status: MissingReportStatus,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this missing report's status.")

        db_missing_report = await self._get_missing_report(missing_report_id, actor)
        if db_missing_report is None:
            raise NotFoundError("Missing report not found.")

        if db_missing_report.report_status in {
            MissingReportStatus.FOUND,
            MissingReportStatus.RETURNED,
            MissingReportStatus.FOSTERED,
            MissingReportStatus.CLOSED,
        }:
            raise InvalidInputError("Missing report status is already final and cannot be changed.")

        if status == MissingReportStatus.LOST:
            return

        try:
            await self.db.execute(
                update(MissingReport)
                .where(
                    MissingReport.id == missing_report_id,
                    MissingReport.is_deleted.is_(False),
                )
                .values(report_status=status)
            )

            await self._update_pet_missing_status(db_missing_report.pet_id, False)

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the missing report status. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the missing report status."
            ) from error

        pet_photo_uuids = await self._get_pet_photo_uuids_by_pet_id(db_missing_report.pet_id)

        if pet_photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_update_payload_task",
                    collection_name="pet_photos",
                    point_ids=pet_photo_uuids,
                    payload={"is_missing": False},
                )

            except Exception as error:
                LOGGER.error(f"Failed to enqueue Qdrant payload update for missing status {missing_report_id}: {error}")

    async def soft_delete(
        self,
        *,
        actor: Actor,
        missing_report_id: int,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to delete this missing report.")

        db_missing_report = await self._get_missing_report(missing_report_id, actor)
        if db_missing_report is None:
            raise NotFoundError("Missing report not found.")

        is_lost = db_missing_report.report_status == MissingReportStatus.LOST

        pet_photo_uuids = []
        if is_lost:
            pet_photo_uuids = await self._get_pet_photo_uuids_by_pet_id(db_missing_report.pet_id)

        try:
            await self.db.execute(
                update(MissingReport)
                .where(
                    MissingReport.id == missing_report_id,
                    MissingReport.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            if is_lost:
                await self._update_pet_missing_status(db_missing_report.pet_id, False)

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the missing report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the missing report."
            ) from error

        if pet_photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_update_payload_task",
                    collection_name="pet_photos",
                    point_ids=pet_photo_uuids,
                    payload={"is_missing": False},
                )

            except Exception as error:
                LOGGER.error(f"Failed to enqueue Qdrant payload update for missing status {missing_report_id}: {error}")

    async def hard_delete(
        self,
        *,
        actor: Actor,
        missing_report_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a missing report.")

        db_missing_report = await self._get_missing_report(missing_report_id)
        if db_missing_report is None:
            raise NotFoundError("Missing report not found.")

        is_lost = db_missing_report.report_status == MissingReportStatus.LOST

        pet_photo_uuids = []
        if is_lost:
            pet_photo_uuids = await self._get_pet_photo_uuids_by_pet_id(db_missing_report.pet_id)

        try:
            await self.db.execute(
                delete(MissingReport)
                .where(MissingReport.id == missing_report_id)
            )

            if is_lost:
                await self._update_pet_missing_status(db_missing_report.pet_id, False)

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the missing report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the missing report."
            ) from error

        if pet_photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_update_payload_task",
                    collection_name="pet_photos",
                    point_ids=pet_photo_uuids,
                    payload={"is_missing": False},
                )

            except Exception as error:
                LOGGER.error(f"Failed to enqueue Qdrant payload update for missing status {missing_report_id}: {error}")

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Union
from uuid import UUID

from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_Distance, ST_GeomFromText, ST_MakeEnvelope, ST_Within
from geoalchemy2.shape import from_shape
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
from shapely.geometry import Point
from sqlalchemy import any_, cast, delete, func, literal, select, union_all, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.enums import ActorType, MimeType, SightingReportStatus
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, MapViewport, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils import queue
from ..core.utils.google_cloud_storage import get_objects_metadata, is_objects_exist
from ..core.utils.pagination import compute_offset
from ..core.utils.qdrant_cloud import client as qdrant_client
from ..core.utils.qdrant_cloud import search_pet
from ..core.utils.update import apply_partial_update
from ..models.missing_report import MissingReport
from ..models.pet import Pet
from ..models.sighting_report import SightingReport
from ..models.sighting_report_image import SightingReportImage
from ..schemas.missing_report import MissingReportRead
from ..schemas.pet import PetRead
from ..schemas.sighting_report import (
    SightingReportCreateWithImages,
    SightingReportRead,
    SightingReportUpdateWithImages,
    SightingReportWithMatches,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SightingReportService:
    db: AsyncSession

    MAX_IMAGES_PER_REPORT: ClassVar[int] = 5
    MAX_TOTAL_IMAGE_SIZE_BYTES: ClassVar[int] = 20 * 1024 * 1024

    MOBILE_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "sighting_location",
        "mobile_user_id",
        "description",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "sighting_location",
        "description",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "mobile_user_id": frozenset({
            FilterOp.EQ,
        }),
        "pet_species": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "sighted_at": frozenset({
            FilterOp.EQ,
            FilterOp.GTE,
            FilterOp.LTE,
        }),
        "sighting_address": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
            FilterOp.IN,
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
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "sighted_at",
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    def _normalize_species(self, value: Any) -> str:
        if value is None:
            return ""

        if hasattr(value, "value"):
            value = value.value

        return str(value).lower().strip()

    async def _get_owned_report_id(self, actor: Actor, report_id: int) -> int | None:
        query = (
            select(SightingReport.id)
            .where(
                SightingReport.id == report_id,
                SightingReport.is_deleted.is_(False),
            )
        )

        if actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(SightingReport.mobile_user_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _require_report_access(self, actor: Actor, report_id: int) -> None:
        if actor.actor_type not in (ActorType.ADMIN_USER, ActorType.MOBILE_USER):
            raise ForbiddenError("You do not have permission to access this sighting report.")

        report_exists = await self._get_owned_report_id(actor, report_id)
        if report_exists is None:
            raise NotFoundError("Sighting report not found.")

    async def _get_sighting_report(
        self,
        report_id: int,
        actor: Actor | None = None,
        with_images: bool = False,
    ) -> SightingReport | None:
        query = select(SightingReport)

        if with_images:
            query = query.options(selectinload(SightingReport.images))

        query = query.where(
            SightingReport.id == report_id,
            SightingReport.is_deleted.is_(False),
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(SightingReport.mobile_user_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _check_object_keys_exist(self, object_keys: list[str]) -> dict[str, dict[str, str]]:
        if not object_keys:
            return {}

        object_existence_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in object_existence_map.items() if not exists]

        if missing_object_keys:
            raise InvalidInputError(
                "Some image files might not have been uploaded. Please upload them and try again."
            )

        return await asyncio.to_thread(get_objects_metadata, object_keys)

    def _build_new_image(
        self,
        report_id: int,
        image: Union[SightingReportCreateWithImages, SightingReportUpdateWithImages],
        image_object_metadata_map: dict,
    ) -> SightingReportImage:
        metadata = image_object_metadata_map.get(image.object_key, {})
        mime_type_raw = metadata.get("mime_type")

        mime_type_enum = None
        if mime_type_raw:
            try:
                mime_type_enum = MimeType(mime_type_raw.lower())
            except ValueError:
                raise InvalidInputError("Image metadata has invalid mime_type. Please re-upload the file.")

        return SightingReportImage(
            sighting_report_id=report_id,
            object_key=image.object_key,
            sort_order=image.sort_order,
            mime_type=mime_type_enum,
        )

    def _soft_delete_removed_images(
        self,
        existing_images: dict[int, SightingReportImage],
        image_ids_from_input: set[int],
    ) -> list[str]:
        now = datetime.now(UTC)
        deleted_uuids = []
        for image_id in set(existing_images.keys()) - image_ids_from_input:
            image = existing_images[image_id]
            image.is_deleted = True
            image.deleted_at = now
            deleted_uuids.append(str(image.uuid))
        return deleted_uuids

    def _check_image_count_limit(
        self,
        image_ids_from_input: set[int],
        new_images: list,
    ) -> None:
        if len(image_ids_from_input) + len(new_images) > self.MAX_IMAGES_PER_REPORT:
            raise InvalidInputError(
                f"You can only have up to {self.MAX_IMAGES_PER_REPORT} images per sighting report."
            )

    def _check_total_image_size(
        self,
        new_images: list,
        image_object_metadata_map: dict[str, dict[str, str | int]],
    ) -> None:
        total_size = sum(
            int(image_object_metadata_map.get(image.object_key, {}).get("_size", 0))
            for image in new_images
        )

        if total_size > self.MAX_TOTAL_IMAGE_SIZE_BYTES:
            limit_mb = self.MAX_TOTAL_IMAGE_SIZE_BYTES // (1024 * 1024)
            raise InvalidInputError(f"Total size of uploaded images exceeds the {limit_mb}MB limit.")

    def _check_image_ids_exist(
        self,
        image_ids_from_input: set[int],
        db_existing_images: dict[int, SightingReportImage],
    ) -> None:
        unknown_ids = image_ids_from_input - db_existing_images.keys()
        if unknown_ids:
            raise NotFoundError("One or more images you're trying to keep were not found.")

    def _update_existing_images(
        self,
        existing_images_from_input: list,
        db_existing_images: dict[int, SightingReportImage],
    ) -> None:
        for image in existing_images_from_input:
            db_existing_images[image.id].sort_order = image.sort_order

    async def _add_new_images(
        self,
        db_report: SightingReport,
        new_images: list,
        image_object_metadata_map: dict[str, dict[str, str]],
    ) -> list[SightingReportImage]:
        new_image_models = []
        for image in new_images:
            new_image = self._build_new_image(db_report.id, image, image_object_metadata_map)
            self.db.add(new_image)
            db_report.images.append(new_image)
            new_image_models.append(new_image)
        return new_image_models

    async def _apply_image_updates(
        self,
        db_report: SightingReport,
        images: list,
    ) -> tuple[list[str], list[SightingReportImage]]:
        new_images = [image for image in images if getattr(image, "id", None) is None]
        existing_images_from_input = [image for image in images if getattr(image, "id", None) is not None]
        image_ids_from_input: set[int] = {image.id for image in existing_images_from_input}

        self._check_image_count_limit(image_ids_from_input, new_images)

        db_existing_images: dict[int, SightingReportImage] = {
            image.id: image for image in db_report.images if not image.is_deleted
        }

        self._check_image_ids_exist(image_ids_from_input, db_existing_images)

        image_object_metadata_map = {}
        if new_images:
            image_object_metadata_map = await self._check_object_keys_exist(
                [image.object_key for image in new_images]
            )

        self._check_total_image_size(new_images, image_object_metadata_map)

        self._update_existing_images(existing_images_from_input, db_existing_images)
        new_image_models = await self._add_new_images(db_report, new_images, image_object_metadata_map)
        deleted_uuids = self._soft_delete_removed_images(db_existing_images, image_ids_from_input)

        return deleted_uuids, new_image_models

    def _build_embedding_payload(
        self,
        report_uuid: UUID,
        species_value: str,
        image_models: list[SightingReportImage],
    ) -> list[dict]:
        return [
            {
                "id": str(image.uuid),
                "image_object_key": image.object_key,
                "payload": {
                    "sighting_report_id": str(report_uuid),
                    "species": species_value,
                },
            }
            for image in image_models
        ]

    def _resolve_reference_point_from_viewport(self, viewport: MapViewport):
        if viewport.user_latitude is not None and viewport.user_longitude is not None:
            return ST_GeomFromText(f"SRID=4326;POINT({viewport.user_longitude} {viewport.user_latitude})")

        center_latitude = (viewport.north + viewport.south) / 2
        center_longitude = (viewport.east + viewport.west) / 2
        return ST_GeomFromText(f"SRID=4326;POINT({center_longitude} {center_latitude})")

    def _build_sighting_reports_within_envelope_query(self, envelope, reference_point):
        return (
            select(
                literal("sighting").label("type"),
                SightingReport.id.label("id"),
                ST_Distance(
                    cast(SightingReport.sighting_location, Geometry("POINT", 4326)), reference_point
                ).label("distance"),
            )
            .where(
                SightingReport.is_deleted.is_(False),
                ST_Within(
                    cast(SightingReport.sighting_location, Geometry("POINT", 4326)), envelope
                ),
            )
        )

    def _build_missing_reports_within_envelope_query(self, envelope, reference_point):
        return (
            select(
                literal("missing").label("type"),
                MissingReport.id.label("id"),
                ST_Distance(
                    cast(MissingReport.last_seen_location, Geometry("POINT", 4326)), reference_point
                ).label("distance"),
            )
            .join(MissingReport.pet)
            .where(
                MissingReport.is_deleted.is_(False),
                Pet.is_deleted.is_(False),
                ST_Within(
                    cast(MissingReport.last_seen_location, Geometry("POINT", 4326)), envelope
                ),
            )
        )

    async def _fetch_sighting_reports_by_ids(self, sighting_report_ids: list[int]) -> dict[int, SightingReport]:
        if not sighting_report_ids:
            return {}

        fetched_sighting_reports = await self.db.execute(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(SightingReport.id == any_(sighting_report_ids), SightingReport.is_deleted.is_(False))
        )
        return {sighting_report.id: sighting_report for sighting_report in fetched_sighting_reports.scalars().all()}

    async def _fetch_missing_reports_by_ids(self, missing_report_ids: list[int]) -> dict[int, MissingReport]:
        if not missing_report_ids:
            return {}

        fetched_missing_reports = await self.db.execute(
            select(MissingReport)
            .options(
                selectinload(MissingReport.pet).options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
            )
            .where(
                MissingReport.id == any_(missing_report_ids),
                MissingReport.is_deleted.is_(False),
            )
        )
        return {missing_report.id: missing_report for missing_report in fetched_missing_reports.scalars().all()}

    def _serialize_viewport_results_ordered_by_distance(
        self,
        ordered_rows,
        sighting_reports_by_id: dict[int, SightingReport],
        missing_reports_by_id: dict[int, MissingReport],
    ) -> list[dict[str, Any]]:
        lookup_and_serializer_by_report_type = {
            "sighting": (sighting_reports_by_id, SightingReportRead.model_validate),
            "missing": (missing_reports_by_id, MissingReportRead.model_validate),
        }

        combined = []
        for row in ordered_rows:
            lookup, serialize = lookup_and_serializer_by_report_type[row.type]
            report = lookup.get(row.id)
            if report is not None:
                combined.append({"type": row.type, "distance": float(row.distance), "data": serialize(report)})

        return combined

    async def _enqueue_nearby_users_notification(
        self,
        *,
        actor: Actor,
        report_id: int,
        pet_label: str,
        longitude: float,
        latitude: float,
        excluded_user_id: int,
    ) -> None:
        await queue.pool.enqueue_job(
            "notify_nearby_alert_center_task",
            event_longitude=longitude,
            event_latitude=latitude,
            notification_title="👀 Pet sighting alert",
            notification_body=f"A {pet_label} was spotted near your alert center. Tap to view details.",
            notification_data={
                "type": "sighting_report_created",
                "sighting_report_id": str(report_id),
                "pet_type": pet_label,
            },
            notification_feature="nearby_report_alerts",
            radius_in_meters=settings.NEARBY_ALERT_CENTER_RADIUS_METERS,
            excluded_user_id=excluded_user_id,
        )

    async def _enqueue_sighting_image_feature_extraction(
        self,
        *,
        images_payload: list[dict],
    ) -> None:
        await queue.pool.enqueue_job(
            "extract_features_task",
            images_payload,
            "report_sightings",
        )

    async def _enqueue_sighting_image_soft_delete_embeddings(
        self,
        *,
        image_uuids: list[str],
    ) -> None:
        await queue.pool.enqueue_job(
            "qdrant_soft_delete_embeddings_task",
            collection_name="report_sightings",
            point_ids=image_uuids,
        )

    async def _enqueue_sighting_image_hard_delete_embeddings(
        self,
        *,
        image_uuids: list[str],
    ) -> None:
        await queue.pool.enqueue_job(
            "qdrant_hard_delete_embeddings_task",
            collection_name="report_sightings",
            point_ids=image_uuids,
        )

    async def create(
        self,
        *,
        actor: Actor,
        user_id: int,
        report_input: SightingReportCreateWithImages,
    ) -> SightingReportRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to create a sighting report.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        images = report_input.images or []
        if images:
            await self._check_object_keys_exist([image.object_key for image in images])

        wkb_location = from_shape(
            Point(
                report_input.sighting_location.longitude,
                report_input.sighting_location.latitude,
            ),
            srid=4326,
        )

        report_model = SightingReport(
            **report_input.model_dump(exclude={"sighting_location", "images"}),
            sighting_location=wkb_location,
            mobile_user_id=user_id,
        )
        self.db.add(report_model)
        await self.db.flush()

        new_image_models = []
        if images:
            image_object_metadata_map = await self._check_object_keys_exist(
                [image.object_key for image in images]
            )
            for image in images:
                new_image = self._build_new_image(report_model.id, image, image_object_metadata_map)
                self.db.add(new_image)
                new_image_models.append(new_image)

        species_value = self._normalize_species(report_input.pet_species)
        pet_label = species_value if species_value in {"dog", "cat"} else "pet"

        new_images_payload = []
        if new_image_models:
            new_images_payload = self._build_embedding_payload(
                report_uuid=report_model.uuid,
                species_value=species_value,
                image_models=new_image_models,
            )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(
                error, "uq_sighting_report_image_sighting_report_id_sort_order_active"
            ):
                raise InvalidInputError("Please arrange the images in a valid order.")

            raise InvalidInputError("Unable to create the sighting report.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the sighting report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the sighting report."
            ) from error

        try:
            await self._enqueue_nearby_users_notification(
                actor=actor,
                report_id=report_model.id,
                pet_label=pet_label,
                longitude=report_input.sighting_location.longitude,
                latitude=report_input.sighting_location.latitude,
                excluded_user_id=user_id,
            )

        except Exception as error:
            LOGGER.warning(f"Failed to enqueue notify_nearby_alert_center_task: {error}")

        if new_images_payload:
            try:
                await self._enqueue_sighting_image_feature_extraction(images_payload=new_images_payload)

            except Exception as error:
                LOGGER.warning(f"Failed to enqueue extract_features_task: {error}")

        result = await self.db.scalar(
            select(SightingReport)
            .options(selectinload(SightingReport.images))
            .where(SightingReport.id == report_model.id)
        )

        return SightingReportRead.model_validate(result)

    async def get_combined_reports_by_viewport(
        self,
        *,
        viewport: MapViewport,
    ) -> list[dict[str, Any]]:
        reference_point = self._resolve_reference_point_from_viewport(viewport)
        envelope = ST_MakeEnvelope(viewport.west, viewport.south, viewport.east, viewport.north, 4326)

        combined_query = union_all(
            self._build_sighting_reports_within_envelope_query(envelope, reference_point),
            self._build_missing_reports_within_envelope_query(envelope, reference_point),
        ).order_by("distance")

        ordered_rows = (await self.db.execute(combined_query)).all()

        sighting_reports_by_id = await self._fetch_sighting_reports_by_ids(
            [row.id for row in ordered_rows if row.type == "sighting"]
        )
        missing_reports_by_id = await self._fetch_missing_reports_by_ids(
            [row.id for row in ordered_rows if row.type == "missing"]
        )

        return self._serialize_viewport_results_ordered_by_distance(
            ordered_rows,
            sighting_reports_by_id,
            missing_reports_by_id,
        )

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
    ) -> PaginatedResponse[SightingReportRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search sighting reports.")

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
                select(SightingReport)
                .options(selectinload(SightingReport.images))
                .where(
                    SightingReport.mobile_user_id == user_id,
                    SightingReport.is_deleted.is_(False),
                )
            )
        else:
            base_query = (
                select(SightingReport)
                .options(selectinload(SightingReport.images))
                .where(SightingReport.is_deleted.is_(False))
            )

        engine = SearchEngine(
            db=self.db,
            model=SightingReport,
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
            serializer=SightingReportRead.model_validate,
        )

        return PaginatedResponse[SightingReportRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_sighting_reports(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
    ) -> PaginatedResponse[SightingReportRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view sighting reports.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(SightingReport)
            .where(SightingReport.is_deleted.is_(False))
        )

        if user_id is not None:
            base_query = base_query.where(SightingReport.mobile_user_id == user_id)

        db_reports = (
            await self.db.execute(
                base_query
                .options(selectinload(SightingReport.images))
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

        return PaginatedResponse[SightingReportRead](
            data=[SightingReportRead.model_validate(report) for report in db_reports],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_sighting_report(
        self,
        *,
        actor: Actor,
        report_id: int,
        with_matches: bool = False,
    ) -> Union[SightingReportRead, SightingReportWithMatches]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this sighting report.")

        db_report = await self._get_sighting_report(report_id, actor, with_images=True)
        if db_report is None:
            raise NotFoundError("Sighting report not found.")

        if not with_matches:
            return SightingReportRead.model_validate(db_report)

        image_uuids = [str(image.uuid) for image in db_report.images]
        if not image_uuids:
            return SightingReportWithMatches.model_validate(db_report)

        points = await asyncio.to_thread(
            qdrant_client.retrieve,
            collection_name="report_sightings",
            ids=image_uuids,
            with_vectors=True,
        )

        if not points:
            return SightingReportWithMatches.model_validate(db_report)

        matched_pets = []
        for point in points:
            embedding = point.vector
            results = await asyncio.to_thread(
                search_pet,
                collection_name="pet_photos",
                query_vector=embedding,
                limit=25,
                score_threshold=0.60,
                query_filter=Filter(
                    must=[FieldCondition(key="is_missing", match=MatchValue(value=True))]
                ),
            )
            for r in results:
                matched_pets.append({
                    "report_image_uuid": point.id,
                    "matched_pet_id": r["payload"]["pet_id"],
                    "score": r["score"],
                    "payload": r["payload"],
                })

        unique_pets = {}
        for match in sorted(matched_pets, key=lambda m: m["score"], reverse=True):
            pet_id = match["matched_pet_id"]
            if pet_id not in unique_pets:
                unique_pets[pet_id] = match
            if len(unique_pets) == 10:
                break

        pet_ids = [m["matched_pet_id"] for m in unique_pets.values()]
        if pet_ids:
            pet_uuids = [UUID(str(x)) for x in pet_ids]
            pets_with_images = (
                await self.db.execute(
                    select(Pet)
                    .options(selectinload(Pet.photos))
                    .where(
                        Pet.uuid == any_(pet_uuids),
                        Pet.is_deleted.is_(False),
                    )
                )
            ).scalars().all()
        else:
            pets_with_images = []

        pets_map = {str(p.uuid): p for p in pets_with_images}
        for match in unique_pets.values():
            pet = pets_map.get(str(match["matched_pet_id"]))
            if pet:
                match["pet"] = PetRead.model_validate(pet).model_dump()

        report_data = SightingReportRead.model_validate(db_report).model_dump()
        report_data["matches"] = list(unique_pets.values())
        return SightingReportWithMatches(**report_data)

    async def update(
        self,
        *,
        actor: Actor,
        report_id: int,
        report_input: SightingReportUpdateWithImages,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this sighting report.")

        db_report = await self._get_sighting_report(report_id, actor, with_images=True)
        if db_report is None:
            raise NotFoundError("Sighting report not found.")

        apply_partial_update(
            target=db_report,
            input=report_input,
            exclude={"sighting_location", "images"},
        )

        deleted_uuids = []
        new_image_models = []
        if report_input.images is not None:
            deleted_uuids, new_image_models = await self._apply_image_updates(db_report, report_input.images)

        species_value = self._normalize_species(db_report.pet_species)

        new_images_payload = []
        if new_image_models:
            new_images_payload = self._build_embedding_payload(
                report_uuid=db_report.uuid,
                species_value=species_value,
                image_models=new_image_models,
            )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(
                error, "uq_sighting_report_image_sighting_report_id_sort_order_active"
            ):
                raise InvalidInputError("Please arrange the images in a valid order.")

            raise InvalidInputError("Unable to update the sighting report.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the sighting report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the sighting report."
            ) from error

        if deleted_uuids:
            try:
                await self._enqueue_sighting_image_soft_delete_embeddings(image_uuids=deleted_uuids)

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_soft_delete_embeddings_task for report_sightings %s: %s",
                    deleted_uuids,
                    error,
                )

        if new_images_payload:
            try:
                await self._enqueue_sighting_image_feature_extraction(images_payload=new_images_payload)

            except Exception as error:
                LOGGER.warning(f"Failed to enqueue feature extraction job: {error}")

    async def update_status(
        self,
        *,
        actor: Actor,
        report_id: int,
        status: SightingReportStatus,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("You do not have permission to update this sighting report's status.")

        try:
            result = await self.db.execute(
                update(SightingReport)
                .where(
                    SightingReport.id == report_id,
                    SightingReport.is_deleted.is_(False),
                )
                .values(report_status=status)
            )
            if result.rowcount == 0:
                raise NotFoundError("Sighting report not found.")

            await self.db.commit()

        except NotFoundError:
            raise

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the sighting report status. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the sighting report status."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        report_id: int,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to delete this sighting report.")

        db_report = await self._get_sighting_report(report_id, actor, with_images=True)
        if db_report is None:
            raise NotFoundError("Sighting report not found.")

        image_uuids = [str(image.uuid) for image in db_report.images]

        statement_report = (
            update(SightingReport)
            .where(
                SightingReport.id == report_id,
                SightingReport.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        statement_images = (
            update(SightingReportImage)
            .where(
                SightingReportImage.sighting_report_id == report_id,
                SightingReportImage.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement_report)
            await self.db.execute(statement_images)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the sighting report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the sighting report."
            ) from error

        if image_uuids:
            try:
                await self._enqueue_sighting_image_soft_delete_embeddings(image_uuids=image_uuids)

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_soft_delete_embeddings_task for report_sightings %s: %s",
                    image_uuids,
                    error,
                )

    async def hard_delete(
        self,
        *,
        actor: Actor,
        report_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a sighting report.")

        db_report = await self._get_sighting_report(report_id, with_images=True)
        if db_report is None:
            raise NotFoundError("Sighting report not found.")

        image_uuids = [str(image.uuid) for image in db_report.images]

        statement = (
            delete(SightingReport)
            .where(SightingReport.id == report_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the sighting report. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the sighting report."
            ) from error

        if image_uuids:
            try:
                await self._enqueue_sighting_image_hard_delete_embeddings(image_uuids=image_uuids)

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_hard_delete_embeddings_task for report_sightings %s: %s",
                    image_uuids,
                    error,
                )

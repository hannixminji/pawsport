import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Union
from uuid import UUID

import httpx
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
from sqlalchemy import any_, delete, func, select, true, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.enums import ActorType, MissingReportStatus
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, MLServiceError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils import queue
from ..core.utils.google_cloud_storage import is_objects_exist
from ..core.utils.pagination import compute_offset
from ..core.utils.qdrant_cloud import search_pet
from ..core.utils.qr_code import generate_qr_and_upload_gcs
from ..core.utils.update import apply_partial_update
from ..models.missing_report import MissingReport
from ..models.mobile_user import MobileUser
from ..models.pet import Pet
from ..models.pet_allergy import PetAllergy
from ..models.pet_medical_condition import PetMedicalCondition
from ..models.pet_medication import PetMedication
from ..models.pet_photo import PetPhoto
from ..models.pet_qr_preference import PetQRPreference
from ..models.pet_schedule import PetSchedule
from ..models.pet_vaccination_record import PetVaccinationRecord
from ..schemas.pet import (
    MissingReportReadWithoutPet,
    OwnerQR,
    PetCreateWithPhotos,
    PetRead,
    PetReadByQR,
    PetSearch,
    PetUpdateWithPhotos,
)
from ..schemas.pet_allergy import PetAllergyRead
from ..schemas.pet_medical_condition import PetMedicalConditionRead
from ..schemas.pet_photo import PetPhotoCreate, PetPhotoRead, PetPhotoUpdate
from ..schemas.pet_qr_default import PetQRDefaultRead
from ..schemas.pet_qr_preference import PetQRPreferenceRead, PetQRPreferenceUpdate
from ..schemas.pet_vaccination_record import PetVaccinationRecordRead

LOGGER = logging.getLogger(__name__)

VALID_SPECIES = frozenset({"cat", "dog"})


@dataclass(slots=True)
class PetService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "owner_id",
        "color",
        "markings",
        "weight_kg",
        "qr_code_object_key",
        "uuid",
        "is_missing",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "color",
        "markings",
        "weight_kg",
        "qr_code_object_key",
        "uuid",
        "is_missing",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "owner_id": frozenset({
            FilterOp.EQ,
        }),
        "name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "species": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "breed": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "sex": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "date_of_birth": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
        "is_sterilized": frozenset({
            FilterOp.EQ,
        }),
        "is_missing": frozenset({
            FilterOp.EQ,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "name",
        "breed",
        "date_of_birth",
        "created_at",
    }

    def _normalize_species(self, value: Any) -> str:
        if value is None:
            return ""

        if hasattr(value, "value"):
            value = value.value

        return str(value).lower().strip()

    async def _get_pet(
        self,
        pet_id: int,
        actor: Actor | None = None,
        with_photos: bool = False,
    ) -> Pet | None:
        query = select(Pet)

        load_options = []
        if with_photos:
             load_options.append(selectinload(Pet.photos))
        load_options.append(selectinload(Pet.qr_preference))

        if load_options:
            query = query.options(*load_options)

        query = query.where(
            Pet.id == pet_id,
            Pet.is_deleted.is_(False),
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(Pet.owner_id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def _validate_photo_object_keys_exist(self, object_keys: list[str]) -> None:
        if not object_keys:
            return

        exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
        missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]

        if missing_object_keys:
            raise InvalidInputError("Some image files might not have been uploaded. Please upload them and try again.")

    async def _validate_photos_with_ml(self, species_value: str, photos: list[PetPhotoCreate]) -> None:
        if not photos:
            return

        validation_payload = [
            {"id": str(photo.sort_order), "image_object_key": photo.object_key}
            for photo in photos
            if photo.object_key
        ]
        if not validation_payload:
            return

        all_sort_orders_sorted = sorted(
            photo.sort_order for photo in photos if photo.object_key
        )
        position_by_sort_order = {
            str(sort_order): idx + 1
            for idx, sort_order in enumerate(all_sort_orders_sorted)
        }

        timeout = httpx.Timeout(connect=20.0, write=30.0, read=60.0, pool=None)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(
                    f"{settings.ML_BASE_URL}/validate_detection",
                    data={
                        "species": species_value,
                        "image_object_keys": json.dumps(validation_payload),
                        "conf_threshold": "0.50",
                    },
                )
                resp.raise_for_status()
                v = resp.json()

            except httpx.ReadTimeout as error:
                LOGGER.warning("validate_detection timeout: %s", error)
                raise MLServiceError("Please try again in a bit.") from error

            except httpx.ConnectError as error:
                LOGGER.warning("validate_detection connect error: %s", error)
                raise MLServiceError("Please try again in a bit.") from error

            except httpx.HTTPStatusError as error:
                LOGGER.warning("validate_detection HTTP %s: %s", error.response.status_code, error.response.text)
                raise MLServiceError("Please try again in a bit.") from error

            except Exception as error:
                LOGGER.exception("validate_detection unexpected error: %s", error)
                raise MLServiceError("Something went wrong. Please try again.") from error

        results = v.get("results", [])
        invalid = [r for r in results if not r.get("valid")]

        if not invalid:
            return

        reasons = {str(r.get("reason") or "") for r in invalid}
        bad_ids = [str(r.get("id")) for r in invalid if r.get("id") is not None]
        bad_ids_sorted = sorted(bad_ids, key=lambda x: int(x) if x.isdigit() else x)
        bad_ids_display = [
            str(position_by_sort_order[x])
            for x in bad_ids_sorted
            if x in position_by_sort_order
        ]

        if len(bad_ids_display) == 1:
            photo_label = f"Photo {bad_ids_display[0]}"
        elif len(bad_ids_display) == 2:
            photo_label = f"Photos {bad_ids_display[0]} and {bad_ids_display[1]}"
        else:
            photo_label = f"Photos {', '.join(bad_ids_display[:-1])}, and {bad_ids_display[-1]}"

        if "wrong_species" in reasons:
            base = (
                f"Hmm, {photo_label} don't seem to be a {species_value}. "
                f"Please upload clear {species_value} photos and try again."
                if bad_ids_display
                else
                f"Hmm, one or more photos don't seem to be a {species_value}. "
                f"Please upload clear {species_value} photos and try again."
            )
        elif "no_detection" in reasons:
            base = (
                f"We couldn't spot a {species_value} in {photo_label}. "
                "Try uploading a clearer, well-lit photo of your pet."
                if bad_ids_display
                else
                f"We couldn't spot a {species_value} in one or more photos. "
                "Try uploading a clearer, well-lit photo of your pet."
            )
        elif "multiple_found" in reasons:
            base = (
                f"{photo_label} seem to have more than one pet in them. "
                "Please upload photos with only one pet visible."
                if bad_ids_display
                else
                "One or more photos seem to have more than one pet in them. "
                "Please upload photos with only one pet visible."
            )
        else:
            base = (
                f"We had trouble processing {photo_label}. "
                "Please try uploading clearer photos."
                if bad_ids_display
                else
                "We had trouble processing one or more photos. "
                "Please try uploading clearer photos."
            )

        raise InvalidInputError(base)

    def _build_new_photo(self, pet_id: int, photo: PetPhotoCreate) -> PetPhoto:
        return PetPhoto(
            pet_id=pet_id,
            object_key=photo.object_key,
            sort_order=photo.sort_order,
        )

    def _check_photo_ids_exist(
        self,
        photo_ids_from_input: set[int],
        db_existing_photos: dict[int, PetPhoto],
    ) -> None:
        unknown_ids = photo_ids_from_input - db_existing_photos.keys()
        if unknown_ids:
            raise NotFoundError("Some profile images you're trying to keep were not found.")

    def _update_existing_photos(
        self,
        existing_photos_from_input: list[PetPhotoUpdate],
        db_existing_photos: dict[int, PetPhoto],
    ) -> None:
        for photo in existing_photos_from_input:
            db_existing_photos[photo.id].sort_order = photo.sort_order

    def _add_new_photos(self, db_pet: Pet, new_photos: list[PetPhotoCreate]) -> list[PetPhoto]:
        new_photo_models = []
        for photo in new_photos:
            new_photo = self._build_new_photo(db_pet.id, photo)
            self.db.add(new_photo)
            db_pet.photos.append(new_photo)
            new_photo_models.append(new_photo)
        return new_photo_models

    def _soft_delete_removed_photos(
        self,
        db_existing_photos: dict[int, PetPhoto],
        photo_ids_from_input: set[int],
    ) -> list[str]:
        now = datetime.now(UTC)
        deleted_uuids = []
        for photo_id in set(db_existing_photos.keys()) - photo_ids_from_input:
            photo = db_existing_photos[photo_id]
            photo.is_deleted = True
            photo.deleted_at = now
            deleted_uuids.append(str(photo.uuid))
        return deleted_uuids

    async def _apply_photo_updates(
        self,
        db_pet: Pet,
        photos: list[Union[PetPhotoCreate, PetPhotoUpdate]],
        skip_existence_check: bool = False,
    ) -> tuple[list[str], list[PetPhoto], list[str]]:
        new_photos: list[PetPhotoCreate] = [p for p in photos if getattr(p, "id", None) is None]
        existing_photos_from_input: list[PetPhotoUpdate] = [p for p in photos if getattr(p, "id", None) is not None]
        photo_ids_from_input: set[int] = {p.id for p in existing_photos_from_input}

        db_existing_photos: dict[int, PetPhoto] = {
            photo.id: photo for photo in db_pet.photos if not photo.is_deleted
        }

        self._check_photo_ids_exist(photo_ids_from_input, db_existing_photos)

        new_object_keys = [new_photo.object_key for new_photo in new_photos if new_photo.object_key]
        if not skip_existence_check and new_object_keys:
            await self._validate_photo_object_keys_exist(new_object_keys)

        self._update_existing_photos(existing_photos_from_input, db_existing_photos)
        new_photo_models = self._add_new_photos(db_pet, new_photos)
        deleted_photo_uuids = self._soft_delete_removed_photos(db_existing_photos, photo_ids_from_input)

        return deleted_photo_uuids, new_photo_models, new_object_keys

    async def _apply_qr_preference_update(
        self,
        pet_id: int,
        qr_preference_input: PetQRPreferenceUpdate,
    ) -> None:
        db_qr_preference = (
            await self.db.execute(
                select(PetQRPreference).where(PetQRPreference.pet_id == pet_id)
            )
        ).scalar_one_or_none()

        if db_qr_preference is None:
            raise NotFoundError("QR preference not found.")

        apply_partial_update(target=db_qr_preference, input=qr_preference_input)

    def _build_embedding_payload(
        self,
        pet_uuid: UUID,
        species_value: str,
        is_missing: bool,
        photo_models: list[PetPhoto],
    ) -> list[dict]:
        return [
            {
                "id": str(photo.uuid),
                "image_object_key": photo.object_key,
                "payload": {
                    "pet_id": str(pet_uuid),
                    "species": species_value,
                    "is_missing": is_missing,
                    "is_deleted": False,
                },
            }
            for photo in photo_models
        ]

    async def create(
        self,
        *,
        actor: Actor,
        user_id: int,
        pet_input: PetCreateWithPhotos,
    ) -> PetRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to create a pet.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        photos = pet_input.photos or []
        object_keys = [p.object_key for p in photos if p.object_key]

        await self._validate_photo_object_keys_exist(object_keys)

        species_value = self._normalize_species(pet_input.species)
        if species_value not in VALID_SPECIES:
            raise InvalidInputError("Invalid pet species. Must be 'cat' or 'dog'.")

        await self._validate_photos_with_ml(species_value, photos)

        try:
            pet_model = Pet(
                **pet_input.model_dump(exclude={"photos", "qr_preference"}),
                owner_id=user_id,
            )
            self.db.add(pet_model)
            await self.db.flush()

            qr_object_key = await asyncio.to_thread(
                generate_qr_and_upload_gcs,
                data=f"{settings.QR_BASE_URL}/{pet_model.uuid}",
                object_key=f"qr_codes/{pet_model.uuid}.png",
                scale=10,
                error="H",
                kind="png",
            )
            pet_model.qr_code_object_key = qr_object_key

            photo_models = [
                PetPhoto(
                    pet_id=pet_model.id,
                    object_key=photo.object_key,
                    sort_order=photo.sort_order,
                )
                for photo in photos
            ]
            self.db.add_all(photo_models)

            qr_preference_model = PetQRPreference(pet_id=pet_model.id, **pet_input.qr_preference.model_dump())
            self.db.add(qr_preference_model)
            pet_model.qr_preference = qr_preference_model

            await self.db.flush()

            new_photos_payload = self._build_embedding_payload(
                pet_uuid=pet_model.uuid,
                species_value=species_value,
                is_missing=False,
                photo_models=photo_models,
            )

            await self.db.commit()

        except IntegrityError:
            await self.db.rollback()

            raise InvalidInputError("Unable to create the pet. Please try again later.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the pet. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the pet."
            ) from error

        try:
            await queue.pool.enqueue_job("extract_features_task", new_photos_payload)
        except Exception as error:
            LOGGER.warning("Failed to enqueue extract_features_task for pet %s: %s", pet_model.id, error)

        db_fresh_pet = (
            await self.db.execute(
                select(Pet)
                .options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
                .where(Pet.id == pet_model.id)
            )
        ).scalar_one()

        return PetRead.model_validate(db_fresh_pet)

    async def search_by_image(
        self,
        *,
        file_content: bytes,
        filename: str,
        content_type: str,
        species: Literal["cat", "dog"],
        is_search_by_missing: bool | None = None,
    ) -> list[PetSearch]:
        allowed_content_types = {"image/jpeg", "image/png"}
        if content_type not in allowed_content_types:
            raise InvalidInputError("Please upload a valid image file — only JPG and PNG formats are supported.")

        timeout = httpx.Timeout(connect=60.0, write=120.0, read=300.0, pool=None)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                files = {"file": (filename, file_content, content_type)}
                response = await client.post(
                    f"{settings.ML_BASE_URL}/search_pet", files=files, data={"species": species}
                )
                response.raise_for_status()
                ml_response = response.json()

            except httpx.ReadTimeout as error:
                raise MLServiceError(
                    "The ML service took too long to respond. Please try again."
                ) from error

            except httpx.ConnectError as error:
                raise MLServiceError(
                    "Unable to connect to the ML service. Please try again later."
                ) from error

            except httpx.HTTPStatusError as error:
                raise MLServiceError(
                    "The ML service returned an unexpected response."
                ) from error

            except Exception as error:
                raise MLServiceError(
                    "Something went wrong while processing the image."
                ) from error

        embedding = ml_response.get("embedding")
        if not embedding or not isinstance(embedding, list):
            raise InvalidInputError(ml_response.get("message", "Failed to detect a valid pet in the image."))

        species_value = self._normalize_species(species)
        if not species_value:
            raise InvalidInputError("Invalid species. Must be 'cat' or 'dog'.")

        query_conditions = [
            FieldCondition(key="species", match=MatchValue(value=species_value)),
        ]

        if is_search_by_missing is not None:
            query_conditions.append(
                FieldCondition(key="is_missing", match=MatchValue(value=is_search_by_missing))
            )

        try:
            search_results = await asyncio.to_thread(
                search_pet,
                query_vector=embedding,
                collection_name="pet_photos",
                limit=5,
                query_filter=Filter(must=query_conditions),
            )
        except Exception as error:
            raise MLServiceError(f"Vector search failed: {error}") from error

        if not search_results:
            return []

        pet_scores: dict[UUID, float] = {}
        for hit in search_results:
            pet_id = UUID(str(hit["payload"]["pet_id"]))
            score = hit["score"]
            pet_scores[pet_id] = max(pet_scores.get(pet_id, 0), score)

        db_pets = (
            await self.db.execute(
                select(Pet)
                .options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
                .where(
                    Pet.uuid.in_(pet_scores.keys()),
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalars().all()

        missing_report_by_pet_id: dict[int, MissingReport] = {}
        if is_search_by_missing:
            pet_ids = [pet.id for pet in db_pets]
            if pet_ids:
                missing_reports = (
                    await self.db.execute(
                        select(MissingReport)
                        .where(
                            MissingReport.pet_id == any_(pet_ids),
                            MissingReport.report_status == MissingReportStatus.LOST,
                            MissingReport.is_deleted.is_(False),
                        )
                    )
                ).scalars().all()
                missing_report_by_pet_id = {missing_report.pet_id: missing_report for missing_report in missing_reports}

        return sorted(
            (
                PetSearch.model_validate(
                    {
                        **PetRead.model_validate(pet).model_dump(),
                        "score": pet_scores.get(pet.uuid, 0),
                        "missing_report": (
                            MissingReportReadWithoutPet.model_validate(missing_report_by_pet_id[pet.id]).model_dump(by_alias=True)
                            if is_search_by_missing and pet.id in missing_report_by_pet_id
                            else None
                        ),
                    }
                )
                for pet in db_pets
            ),
            key=lambda pet: pet.score,
            reverse=True,
        )

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
    ) -> PaginatedResponse[PetRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search pets.")

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
                select(Pet)
                .options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
                .where(
                    Pet.owner_id == user_id,
                    Pet.is_deleted.is_(False),
                )
            )
        else:
            base_query = (
                select(Pet)
                .options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
                .where(Pet.is_deleted.is_(False))
            )

        engine = SearchEngine(
            db=self.db,
            model=Pet,
            blacklisted_columns=blacklisted,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=5,
        )

        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=PetRead.model_validate,
        )

        return PaginatedResponse[PetRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_pets(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
        user_id: int | None = None,
    ) -> PaginatedResponse[PetRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view pets.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        base_query = (
            select(Pet)
            .where(Pet.is_deleted.is_(False))
        )

        if user_id is not None:
            base_query = base_query.where(Pet.owner_id == user_id)

        db_pets = (
            await self.db.execute(
                base_query
                .options(
                    selectinload(Pet.photos),
                    selectinload(Pet.qr_preference),
                )
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

        return PaginatedResponse[PetRead](
            data=[PetRead.model_validate(pet) for pet in db_pets],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_pet(
        self,
        *,
        actor: Actor,
        pet_id: int,
    ) -> PetRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this pet.")

        db_pet = await self._get_pet(pet_id, actor, with_photos=True)
        if db_pet is None:
            raise NotFoundError("Pet not found.")

        return PetRead.model_validate(db_pet)

    async def get_pet_by_qr(self, pet_uuid: UUID) -> PetReadByQR:
        db_pet = (
            await self.db.execute(
                select(Pet)
                .options(
                    selectinload(Pet.owner).selectinload(MobileUser.pet_qr_default),
                    selectinload(Pet.photos),
                    selectinload(Pet.allergies),
                    selectinload(Pet.medical_conditions),
                    selectinload(Pet.vaccination_records).selectinload(PetVaccinationRecord.attachments),
                    selectinload(Pet.qr_preference),
                )
                .where(
                    Pet.uuid == pet_uuid,
                    Pet.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

        if db_pet is None:
            raise NotFoundError("Pet not found.")

        qr_default = (
            PetQRDefaultRead.model_validate(db_pet.owner.pet_qr_default)
            if db_pet.owner and db_pet.owner.pet_qr_default
            else None
        )

        qr_preference = (
            PetQRPreferenceRead.model_validate(db_pet.qr_preference)
            if db_pet.qr_preference
            else None
        )

        return PetReadByQR.from_data(
            owner=OwnerQR.model_validate(db_pet.owner),
            name=db_pet.name,
            species=db_pet.species,
            breed=db_pet.breed,
            sex=db_pet.sex,
            is_sterilized=db_pet.is_sterilized,
            date_of_birth=db_pet.date_of_birth,
            is_missing=db_pet.is_missing,
            photos=[PetPhotoRead.model_validate(pet_photo) for pet_photo in db_pet.photos],
            allergies=[PetAllergyRead.model_validate(pet_allergy) for pet_allergy in db_pet.allergies],
            medical_conditions=[
                PetMedicalConditionRead.model_validate(pet_medical_condition)
                for pet_medical_condition in db_pet.medical_conditions
            ],
            vaccination_records=[
                PetVaccinationRecordRead.model_validate(pet_vaccination_record)
                for pet_vaccination_record in db_pet.vaccination_records
            ],
            weight_kg=db_pet.weight_kg,
            color=db_pet.color,
            markings=db_pet.markings,
            qr_code_url=db_pet.qr_code_url,
            defaults=qr_default,
            preference=qr_preference,
        )

    async def update(
        self,
        *,
        actor: Actor,
        pet_id: int,
        pet_input: PetUpdateWithPhotos,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this pet.")

        db_pet = await self._get_pet(pet_id, actor, with_photos=True)
        if db_pet is None:
            raise NotFoundError("Pet not found.")

        pet_species = self._normalize_species(db_pet.species)

        if pet_input.photos is not None:
            new_photos = [photo for photo in pet_input.photos if getattr(photo, "id", None) is None]
            new_object_keys = [photo.object_key for photo in new_photos if photo.object_key]
            if new_object_keys:
                await self._validate_photo_object_keys_exist(new_object_keys)
                await self._validate_photos_with_ml(pet_species, new_photos)

        apply_partial_update(
            target=db_pet,
            input=pet_input,
            exclude={"photos", "qr_preference"},
        )

        deleted_photo_uuids: list[str] = []
        new_photo_models: list[PetPhoto] = []
        if pet_input.photos is not None:
            (
                deleted_photo_uuids,
                new_photo_models,
                _,
            ) = await self._apply_photo_updates(
                db_pet=db_pet,
                photos=pet_input.photos,
                skip_existence_check=True,
            )

        if pet_input.qr_preference is not None:
            await self._apply_qr_preference_update(pet_id, pet_input.qr_preference)

        await self.db.flush()

        new_photos_payload: list[dict] = []
        if new_photo_models:
            new_photos_payload = self._build_embedding_payload(
                pet_uuid=db_pet.uuid,
                species_value=pet_species,
                is_missing=db_pet.is_missing,
                photo_models=new_photo_models,
            )

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the pet. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the pet."
            ) from error

        if deleted_photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_soft_delete_embeddings_task",
                    collection_name="pet_photos",
                    point_ids=deleted_photo_uuids,
                )

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_soft_delete_embeddings_task for pet_photos %s: %s",
                    deleted_photo_uuids,
                    error,
                )

        if new_photos_payload:
            try:
                await queue.pool.enqueue_job(
                    "extract_features_task",
                    new_photos_payload,
                )

            except Exception as error:
                LOGGER.warning("Failed to enqueue feature extraction job: %s", error)

    async def soft_delete(
        self,
        *,
        actor: Actor,
        pet_id: int,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to delete this pet.")

        owner_filter = (
            Pet.owner_id == actor.id
            if actor.actor_type == ActorType.MOBILE_USER
            else true()
        )

        try:
            photo_uuids = (
                await self.db.execute(
                    select(PetPhoto.uuid)
                    .where(
                        PetPhoto.pet_id == pet_id,
                        PetPhoto.is_deleted.is_(False),
                    )
                )
            ).scalars().all()

            deleted = (
                await self.db.execute(
                    update(Pet)
                    .where(
                        Pet.id == pet_id,
                        Pet.is_deleted.is_(False),
                        owner_filter,
                    )
                    .values(
                        deleted_at=func.now(),
                        is_deleted=True,
                    )
                    .returning(Pet.id)
                )
            ).scalar_one_or_none()
            if deleted is None:
                raise NotFoundError("Pet not found.")

            await self.db.execute(
                update(PetPhoto)
                .where(
                    PetPhoto.pet_id == pet_id,
                    PetPhoto.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(PetAllergy)
                .where(
                    PetAllergy.pet_id == pet_id,
                    PetAllergy.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(PetMedicalCondition)
                .where(
                    PetMedicalCondition.pet_id == pet_id,
                    PetMedicalCondition.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(PetMedication)
                .where(
                    PetMedication.pet_id == pet_id,
                    PetMedication.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(PetVaccinationRecord)
                .where(
                    PetVaccinationRecord.pet_id == pet_id,
                    PetVaccinationRecord.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(PetSchedule)
                .where(
                    PetSchedule.pet_id == pet_id,
                    PetSchedule.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.execute(
                update(MissingReport)
                .where(
                    MissingReport.pet_id == pet_id,
                    MissingReport.is_deleted.is_(False),
                )
                .values(
                    deleted_at=func.now(),
                    is_deleted=True,
                )
            )

            await self.db.commit()

        except NotFoundError:
            raise

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the pet. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the pet."
            ) from error

        if photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_soft_delete_embeddings_task",
                    collection_name="pet_photos",
                    point_ids=photo_uuids,
                )

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_soft_delete_embeddings_task for pet_photos %s: %s",
                    photo_uuids,
                    error,
                )

    async def hard_delete(
        self,
        *,
        actor: Actor,
        pet_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a pet.")

        db_pet = await self._get_pet(pet_id, with_photos=True)
        if db_pet is None:
            raise NotFoundError("Pet not found.")

        photo_uuids = [str(photo.uuid) for photo in db_pet.photos]

        statement = (
            delete(Pet)
            .where(Pet.id == pet_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the pet. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the pet."
            ) from error

        if photo_uuids:
            try:
                await queue.pool.enqueue_job(
                    "qdrant_hard_delete_embeddings_task",
                    collection_name="pet_photos",
                    point_ids=photo_uuids,
                )

            except Exception as error:
                LOGGER.warning(
                    "Failed to enqueue qdrant_hard_delete_embeddings_task for pet_photos %s: %s",
                    photo_uuids,
                    error,
                )

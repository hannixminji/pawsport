import asyncio
import json
import logging
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, Union
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastcrud import PaginatedListResponse, compute_offset, paginated_response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qdrant_client.http.models import FieldCondition, Filter, MatchValue
from sqlalchemy import and_, func, not_, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...api.dependencies import get_authenticated_superuser, get_authenticated_user
from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import (
    BadRequestException,
    CustomException,
    ForbiddenException,
    NotFoundException,
)
from ...core.utils import queue
from ...core.utils.cache import cache
from ...core.utils.google_cloud_storage import is_objects_exist
from ...core.utils.qdrant_cloud import delete_embedding, search_pet
from ...core.utils.qr_code import generate_qr_and_upload_gcs
from ...models.missing_report import MissingReport
from ...models.pet import Pet
from ...models.pet_allergy import PetAllergy
from ...models.pet_medical_condition import PetMedicalCondition
from ...models.pet_medication import PetMedication
from ...models.pet_profile_image import PetProfileImage
from ...models.pet_schedule import PetSchedule
from ...models.pet_vaccination_record import PetVaccinationRecord
from ...models.user import User
from ...schemas.pet import PetCreateWithProfileImages, PetRead, PetReadByQr, PetSearch, PetUpdateWithProfileImages
from ...schemas.user import UserRead

LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["pets"])

TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "core" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def normalize_species(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    return str(value).lower().strip()


class SortOrder(StrEnum):
    ASC = "asc"
    DESC = "desc"


class FilterOp(StrEnum):
    EQ = "eq"
    ILIKE = "ilike"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class PetSortBy(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"
    TYPE = "type"
    BREED = "breed"
    SEX = "sex"
    DATE_OF_BIRTH = "date_of_birth"


class PetFilterField(StrEnum):
    NAME = "name"
    TYPE = "type"
    BREED = "breed"
    SEX = "sex"
    COLOR = "color"
    IS_STERILIZED = "is_sterilized"
    CREATED_AT = "created_at"
    DATE_OF_BIRTH = "date_of_birth"


class WhereRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rule"]
    field: PetFilterField
    op: FilterOp
    value: Any


class WhereGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["group"]
    op: Literal["and", "or"]
    conditions: list["WhereNode"] = Field(min_length=1, max_length=50)


class WhereNot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["not"]
    condition: "WhereNode"


WhereNode = Annotated[Union[WhereRule, WhereGroup, WhereNot], Field(discriminator="type")]


class PetSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(1, ge=1)
    items_per_page: int = Field(10, ge=1, le=100)

    sort_by: PetSortBy = PetSortBy.CREATED_AT
    sort_order: SortOrder = SortOrder.DESC

    where: WhereNode | None = None

    @model_validator(mode="after")
    def limit_complexity(self):
        def count_nodes(node: WhereNode, depth: int = 0) -> int:
            if depth > 10:
                raise ValueError("where is too deeply nested")

            if isinstance(node, WhereRule):
                return 1

            if isinstance(node, WhereNot):
                return 1 + count_nodes(node.condition, depth + 1)

            total = 1
            for child in node.conditions:
                total += count_nodes(child, depth + 1)
            return total

        if self.where is not None:
            total = count_nodes(self.where, 0)
            if total > 200:
                raise ValueError("where is too large")
        return self


def build_where(node: WhereNode, filter_columns: dict[PetFilterField, Any]):  # noqa: C901
    if isinstance(node, WhereRule):
        column = filter_columns[node.field]
        value = node.value

        if node.field in {PetFilterField.TYPE, PetFilterField.SEX}:
            if node.op not in {FilterOp.EQ, FilterOp.IN}:
                raise BadRequestException(f"{node.field.value} only supports eq or in.")

        if node.field == PetFilterField.IS_STERILIZED:
            if node.op != FilterOp.EQ:
                raise BadRequestException("is_sterilized only supports eq.")
            if not isinstance(value, bool):
                raise BadRequestException("is_sterilized value must be boolean.")

        if node.field in {PetFilterField.NAME, PetFilterField.BREED, PetFilterField.COLOR}:
            if node.op not in {FilterOp.EQ, FilterOp.ILIKE, FilterOp.IN}:
                raise BadRequestException(f"{node.field.value} only supports eq, ilike, or in.")

        if node.op == FilterOp.EQ:
            return column == value

        if node.op == FilterOp.ILIKE:
            if not isinstance(value, str):
                raise BadRequestException("ILIKE value must be a string.")
            return column.ilike(f"%{value}%")

        if node.op == FilterOp.GTE:
            return column >= value

        if node.op == FilterOp.LTE:
            return column <= value

        if node.op == FilterOp.IN:
            if not isinstance(value, list) or not value:
                raise BadRequestException("IN value must be a non-empty list.")
            return column.in_(value)

        raise BadRequestException("Invalid filter operator.")

    if isinstance(node, WhereNot):
        return not_(build_where(node.condition, filter_columns))

    children = [build_where(child, filter_columns) for child in node.conditions]
    return and_(*children) if node.op == "and" else or_(*children)


@router.post("/{username}/pet", response_model=PetRead, status_code=201)
async def write_pet(
    request: Request,
    username: str,
    pet: PetCreateWithProfileImages,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> PetRead:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    object_keys = [pi.image_object_key for pi in (pet.profile_images or []) if pi.image_object_key]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [k for k, ok in exists_map.items() if not ok]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    species_value = normalize_species(pet.type)
    if species_value not in {"cat", "dog"}:
        raise BadRequestException("Invalid pet type. Must be 'cat' or 'dog'.")

    validation_payload = [{"id": str(i), "image_object_key": k} for i, k in enumerate(object_keys)]

    ml_url = "http://ml:9000/validate_detection"
    timeout = httpx.Timeout(connect=20.0, write=30.0, read=60.0, pool=None)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                ml_url,
                data={
                    "species": species_value,
                    "image_object_keys": json.dumps(validation_payload),
                    "conf_threshold": "0.50",
                },
            )
            resp.raise_for_status()
            v = resp.json()

        except httpx.ReadTimeout as e:
            LOGGER.warning("validate_detection timeout: %s", e)
            raise CustomException(503, "Please try again in a bit.")

        except httpx.ConnectError as e:
            LOGGER.warning("validate_detection connect error: %s", e)
            raise CustomException(503, "Please try again in a bit.")

        except httpx.HTTPStatusError as e:
            LOGGER.warning("validate_detection HTTP %s: %s", e.response.status_code, e.response.text)
            raise CustomException(503, "Please try again in a bit.")

        except Exception as e:
            LOGGER.exception("validate_detection unexpected error: %s", e)
            raise CustomException(500, "Something went wrong. Please try again.")

    results = v.get("results", [])
    invalid = [r for r in results if not r.get("valid")]

    if invalid:
        reasons = {str(r.get("reason") or "") for r in invalid}
        bad_ids = [str(r.get("id")) for r in invalid if r.get("id") is not None]
        bad_ids_sorted = sorted(bad_ids, key=lambda x: int(x) if x.isdigit() else x)
        bad_label = ", ".join(str(int(x) + 1) for x in bad_ids_sorted if x.isdigit())

        if "wrong_species" in reasons:
            base = f"One or more photos don’t look like a {species_value}. Please upload clear {species_value} photos."
        elif "no_detection" in reasons:
            base = f"We couldn’t find a {species_value} in one or more photos. Please upload clearer photos."
        elif "multiple_found" in reasons:
            base = "We detected more than one pet in one or more photos. Please upload photos with only one pet."
        else:
            base = "One or more photos can’t be used. Please upload clearer photos."

        if bad_label:
            raise BadRequestException(f"{base} (Problem photos: {bad_label})")
        raise BadRequestException(base)

    pet_model = Pet(**pet.model_dump(exclude={"profile_images"}), owner_id=db_user_id)
    db.add(pet_model)
    await db.flush()

    qr_object_key = generate_qr_and_upload_gcs(
        data=f"http://localhost:8000/api/v1/pet/qr/{pet_model.uuid}",
        object_key=f"qr_codes/{pet_model.uuid}.png",
        scale=10,
        error="H",
        kind="png"
    )
    pet_model.qr_code_image_object_key = qr_object_key

    profile_image_models: list[PetProfileImage] = []
    for profile_image in pet.profile_images:
        profile_image_model = PetProfileImage(**profile_image.model_dump(), pet_id=pet_model.id)
        db.add(profile_image_model)
        profile_image_models.append(profile_image_model)

    await db.flush()

    new_profile_images = [
        {
            "id": str(profile_image.uuid),
            "image_object_key": profile_image.image_object_key,
            "payload": {
                "pet_id": str(pet_model.uuid),
                "species": species_value,
                "is_missing": False
            }
        }
        for profile_image in profile_image_models
    ]

    try:
        await db.commit()
    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_pet_primary_image" in str(error.orig):
            raise BadRequestException("A pet can only have one primary profile image.")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the pet. Please try again later."
        )

    try:
        await queue.pool.enqueue_job("extract_features_task", new_profile_images)
    except Exception as error:
        LOGGER.warning(f"Failed to enqueue extract_features_task for pet {pet_model.id}: {error}")

    await db.refresh(pet_model)

    return PetRead.model_validate(pet_model)


@router.post("/search_pet", response_model=list[PetSearch])
async def search_pets(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    file: UploadFile = File(...),
    species: Literal["cat", "dog"] = Form(...),
    is_search_by_missing: bool | None = None,
) -> list[PetSearch]:
    allowed_types = {"image/jpeg", "image/png"}

    if file.content_type not in allowed_types:
        raise BadRequestException(
            "Please upload a valid image file — only JPG and PNG formats are supported."
        )

    ml_url = "http://ml:9000/search_pet"

    timeout = httpx.Timeout(
        connect=60.0,
        write=120.0,
        read=300.0,
        pool=None,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            files = {"file": (file.filename, await file.read(), file.content_type)}
            response = await client.post(ml_url, files=files, data={"species": species})
            response.raise_for_status()
            ml_response = response.json()
        except httpx.ReadTimeout:
            raise CustomException(503, "The ML service took too long to respond. Please try again.")
        except httpx.ConnectError:
            raise CustomException(503, "Unable to connect to the ML service. Please try again later.")
        except httpx.HTTPStatusError:
            raise CustomException(502, "The ML service returned an unexpected response.")
        except Exception:
            raise CustomException(500, "Something went wrong while processing the image.")

    if "embedding" not in ml_response:
        raise BadRequestException(ml_response.get("message", "Failed to detect a valid pet in the image."))

    embedding = ml_response["embedding"]

    if not embedding or not isinstance(embedding, list):
        raise BadRequestException(ml_response.get("message", "Failed to detect a valid pet in the image."))

    species_query = normalize_species(species)
    if not species_query:
        raise BadRequestException("Invalid species. Must be 'cat' or 'dog'.")

    query_conditions = [
        FieldCondition(
            key="species",
            match=MatchValue(value=species_query),
        )
    ]

    if is_search_by_missing is not None:
        query_conditions.append(
            FieldCondition(
                key="is_missing",
                match=MatchValue(value=is_search_by_missing),
            )
        )

    try:
        search_results = await asyncio.to_thread(
            search_pet,
            query_vector=embedding,
            collection_name="pet_profile_images",
            limit=5,
            query_filter=Filter(must=query_conditions),
        )
    except Exception as e:
        raise BadRequestException(f"Vector search failed: {e}")

    if not search_results:
        return []

    pet_scores: dict[UUID, float] = {}
    for hit in search_results:
        pet_id = UUID(str(hit["payload"]["pet_id"]))
        score = hit["score"]
        pet_scores[pet_id] = max(pet_scores.get(pet_id, 0), score)

    query = select(Pet).options(selectinload(Pet.profile_images)).where(
        Pet.uuid.in_(pet_scores.keys()),
        ~Pet.is_deleted,
    )

    pets = (await db.execute(query)).scalars().all()

    data = sorted(
        (
            PetSearch.model_validate(
                {**PetRead.model_validate(pet).model_dump(), "score": pet_scores.get(pet.uuid, 0)}
            )
            for pet in pets
        ),
        key=lambda pet: pet.score,
        reverse=True,
    )

    return data


@router.post("/{username}/pets/search", response_model=PaginatedListResponse[PetRead])
async def search_user_pets(
    request: Request,
    username: str,
    values: PetSearchRequest,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id).where(
                User.username == username,
                ~User.is_deleted,
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    filter_columns = {
        PetFilterField.NAME: Pet.name,
        PetFilterField.TYPE: Pet.type,
        PetFilterField.BREED: Pet.breed,
        PetFilterField.SEX: Pet.sex,
        PetFilterField.COLOR: Pet.color,
        PetFilterField.IS_STERILIZED: Pet.is_sterilized,
        PetFilterField.CREATED_AT: Pet.created_at,
        PetFilterField.DATE_OF_BIRTH: Pet.date_of_birth,
    }

    sort_columns = {
        PetSortBy.CREATED_AT: Pet.created_at,
        PetSortBy.NAME: Pet.name,
        PetSortBy.TYPE: Pet.type,
        PetSortBy.BREED: Pet.breed,
        PetSortBy.SEX: Pet.sex,
        PetSortBy.DATE_OF_BIRTH: Pet.date_of_birth,
    }

    where_clauses = [
        Pet.owner_id == db_user_id,
        ~Pet.is_deleted,
    ]

    if values.where is not None:
        where_clauses.append(build_where(values.where, filter_columns))

    sort_column = sort_columns.get(values.sort_by)
    if not sort_column:
        raise BadRequestException("Invalid sort_by field.")

    order_by_clause = sort_column.asc() if values.sort_order == SortOrder.ASC else sort_column.desc()

    pets = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(*where_clauses)
            .order_by(order_by_clause)
            .offset(compute_offset(values.page, values.items_per_page))
            .limit(values.items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Pet)
            .where(*where_clauses)
        )
    ).scalar_one()

    pets_data = {
        "data": [PetRead.model_validate(pet) for pet in pets],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(
        crud_data=pets_data,
        page=values.page,
        items_per_page=values.items_per_page
    )
    return response


@router.get("/pets", response_model=PaginatedListResponse[PetRead])
async def read_all_pets(
    request: Request,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    pets_with_profile_images = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(~Pet.is_deleted)
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Pet)
            .where(~Pet.is_deleted)
        )
    ).scalar_one()

    pets_data = {
        "data": [PetRead.from_orm(pet) for pet in pets_with_profile_images],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=pets_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/{username}/pets", response_model=PaginatedListResponse[PetRead])
@cache(
    key_prefix="{username}_pets:page_{page}:items_per_page:{items_per_page}",
    resource_id_name="username",
    expiration=60,
)
async def read_pets(
    request: Request,
    username: str,
    db: Annotated[AsyncSession, Depends(async_get_db)],
    page: int = 1,
    items_per_page: int = 10,
) -> dict[str, Any]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    pets_with_profile_images = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
            .offset(compute_offset(page, items_per_page))
            .limit(items_per_page)
        )
    ).scalars().all()

    total_count = (
        await db.execute(
            select(func.count())
            .select_from(Pet)
            .where(
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one()

    pets_data = {
        "data": [PetRead.from_orm(pet) for pet in pets_with_profile_images],
        "total_count": total_count
    }

    response: dict[str, Any] = paginated_response(crud_data=pets_data, page=page, items_per_page=items_per_page)
    return response


@router.get("/{username}/pet/{id}", response_model=PetRead)
@cache(key_prefix="{username}_pet_cache", resource_id_name="id")
async def read_pet(
    request: Request, username: str, id: int, db: Annotated[AsyncSession, Depends(async_get_db)]
) -> PetRead:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if db_pet is None:
        raise NotFoundException("Pet not found")

    return PetRead.model_validate(db_pet)


@router.get("/pet/qr/{uuid}", response_class=HTMLResponse)
async def read_pet_by_qr(
    request: Request,
    uuid: UUID,
    db: AsyncSession = Depends(async_get_db),
):
    db_pet = (
        await db.execute(
            select(Pet)
            .options(
                selectinload(Pet.owner),
                selectinload(Pet.profile_images),
                selectinload(Pet.allergies),
                selectinload(Pet.medical_conditions),
                selectinload(Pet.vaccination_records),
            )
            .where(
                Pet.uuid == uuid,
                ~Pet.is_deleted,
            )
        )
    ).scalar_one_or_none()

    if not db_pet:
        raise NotFoundException("Pet not found")

    pet_payload = PetReadByQr.model_validate(db_pet)

    accept = (request.headers.get("accept") or "").lower()

    if "application/json" in accept:
        return JSONResponse(content=pet_payload.model_dump(mode="json"))

    return templates.TemplateResponse(
        "pet_qr.html",
        {
            "request": request,
            "pet": pet_payload.model_dump(mode="python"),
            "today": date.today(),
        },
    )


@router.patch("/{username}/pet/{id}")
@cache("{username}_pet_cache", resource_id_name="id", pattern_to_invalidate_extra=["{username}_pets:*"])
async def patch_pet(
    request: Request,
    username: str,
    id: int,
    values: PetUpdateWithProfileImages,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    for field, value in values.model_dump(exclude_unset=True, exclude={"profile_images"}).items():
        setattr(db_pet, field, value)

    object_keys = [
        profile_image.image_object_key
        for profile_image in values.profile_images
        if not getattr(profile_image, "id", None) and getattr(profile_image, "image_object_key", None) is not None
    ]
    exists_map = await asyncio.to_thread(is_objects_exist, object_keys)
    missing_object_keys = [object_key for object_key, exists in exists_map.items() if not exists]
    if missing_object_keys:
        raise BadRequestException("Some image files might not have been uploaded. Please upload them and try again.")

    existing_profile_images = {profile_image.id: profile_image for profile_image in db_pet.profile_images}
    updated_profile_image_ids = {
        profile_image.id
        for profile_image in values.profile_images
        if getattr(profile_image, "id", None) is not None
    }

    invalid_ids = updated_profile_image_ids - set(existing_profile_images.keys())
    if invalid_ids:
        raise NotFoundException("Some profile images do not exist.")

    deleted_profile_image_ids = list(set(existing_profile_images) - updated_profile_image_ids)
    deleted_image_uuids = [str(existing_profile_images[image_id].uuid) for image_id in deleted_profile_image_ids]

    now = datetime.now(UTC)
    for profile_image_id in deleted_profile_image_ids:
        profile_image = existing_profile_images[profile_image_id]
        profile_image.is_deleted = True
        profile_image.deleted_at = now

    new_profile_image_models = []
    new_profile_images_payload = []

    for profile_image in values.profile_images:
        if getattr(profile_image, "id", None):
            existing_image = existing_profile_images[profile_image.id]
            existing_image.sort_order = profile_image.sort_order
            existing_image.is_primary = profile_image.is_primary
        elif getattr(profile_image, "image_object_key", None):
            new_profile_image = PetProfileImage(
                pet_id=db_pet.id,
                image_object_key=profile_image.image_object_key,
                sort_order=profile_image.sort_order,
                is_primary=profile_image.is_primary
            )
            db.add(new_profile_image)
            db_pet.profile_images.append(new_profile_image)
            new_profile_image_models.append(new_profile_image)

    await db.flush()

    primary_images = [
        profile_image for profile_image in db_pet.profile_images
        if not profile_image.is_deleted and profile_image.is_primary
    ]
    if len(primary_images) == 0:
        raise BadRequestException("A pet must have one primary profile image")
    if len(primary_images) > 1:
        raise BadRequestException("A pet can only have one primary profile image")

    if new_profile_image_models:
        species_value = normalize_species(db_pet.type)

        new_profile_images_payload = [
            {
                "id": str(profile_image.uuid),
                "image_object_key": profile_image.image_object_key,
                "payload": {
                    "pet_id": str(db_pet.uuid),
                    "species": species_value,
                    "is_missing": False
                }
            }
            for profile_image in new_profile_image_models
        ]

    try:
        await db.commit()

        if deleted_image_uuids:
            try:
                await asyncio.to_thread(delete_embedding, "pet_profile_images", deleted_image_uuids)
            except Exception as error:
                LOGGER.warning(
                    f"Failed to delete embeddings for pet_profile_images {deleted_image_uuids}: {error}"
                )

        if new_profile_images_payload:
            try:
                await queue.pool.enqueue_job("extract_features_task", new_profile_images_payload)
            except Exception as error:
                LOGGER.warning(f"Failed to enqueue feature extraction job: {error}")

    except SQLAlchemyError as error:
        await db.rollback()

        if isinstance(error, IntegrityError) and "uq_pet_primary_image" in str(error.orig):
            raise BadRequestException("A pet can have only one primary profile image")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the pet. Please try again later."
        )

    return {"message": "Pet updated"}


@router.delete("/{username}/pet/{id}")
@cache("{username}_pet_cache", resource_id_name="id", to_invalidate_extra={"{username}_pets": "{username}"})
async def erase_pet(
    request: Request,
    username: str,
    id: int,
    # current_user: Annotated[UserRead, Depends(get_authenticated_user)],
    db: Annotated[AsyncSession, Depends(async_get_db)],
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    # if current_user.id != db_user_id:
    #     raise ForbiddenException()

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                Pet.owner_id == db_user_id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    profile_image_uuids = [str(profile_image.uuid) for profile_image in db_pet.profile_images]

    now = datetime.now(UTC)
    db_pet.is_deleted = True
    db_pet.deleted_at = now
    db.add(db_pet)

    try:
        await db.execute(
            update(PetProfileImage)
            .where(
                PetProfileImage.pet_id == db_pet.id,
                ~PetProfileImage.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(PetVaccinationRecord)
            .where(
                PetVaccinationRecord.pet_id == db_pet.id,
                ~PetVaccinationRecord.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(PetAllergy)
            .where(
                PetAllergy.pet_id == db_pet.id,
                ~PetAllergy.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(PetMedication)
            .where(
                PetMedication.pet_id == db_pet.id,
                ~PetMedication.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(PetMedicalCondition)
            .where(
                PetMedicalCondition.pet_id == db_pet.id,
                ~PetMedicalCondition.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(PetSchedule)
            .where(
                PetSchedule.pet_id == db_pet.id,
                ~PetSchedule.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.execute(
            update(MissingReport)
            .where(
                MissingReport.pet_id == db_pet.id,
                ~MissingReport.is_deleted
            )
            .values(
                is_deleted=True,
                deleted_at=now
            )
        )

        await db.commit()

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet. Please try again later."
        )

    if profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", profile_image_uuids)
        except Exception as error:
            LOGGER.warning(f"Failed to delete embeddings for pet_profile_images {profile_image_uuids}: {error}")

    return {"message": "Pet deleted"}


@router.delete("/{username}/db_pet/{id}", dependencies=[Depends(get_authenticated_superuser)])
@cache("{username}_pet_cache", resource_id_name="id", to_invalidate_extra={"{username}_pets": "{username}"})
async def erase_db_pet(
    request: Request,
    username: str,
    id: int,
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> dict[str, str]:
    db_user_id = (
        await db.execute(
            select(User.id)
            .where(
                User.username == username,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_user_id:
        raise NotFoundException("User not found")

    db_pet = (
        await db.execute(
            select(Pet)
            .options(selectinload(Pet.profile_images))
            .where(
                Pet.id == id,
                ~Pet.is_deleted
            )
        )
    ).scalar_one_or_none()
    if not db_pet:
        raise NotFoundException("Pet not found")

    profile_image_uuids = [str(profile_image.uuid) for profile_image in db_pet.profile_images]

    try:
        await db.delete(db_pet)
        await db.commit()

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting the pet. Please try again later."
        )

    if profile_image_uuids:
        try:
            await asyncio.to_thread(delete_embedding, "pet_profile_images", profile_image_uuids)
        except Exception as error:
            LOGGER.warning(f"Failed to delete embeddings for pet_profile_images {profile_image_uuids}: {error}")

    return {"message": "Pet deleted from the database"}

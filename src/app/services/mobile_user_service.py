import logging
from dataclasses import dataclass

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import ActorType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.security import get_password_hash, verify_password
from ..core.utils.google_cloud_storage import is_object_exists
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.mobile_user import MobileUser
from ..schemas.mobile_user import MobileUserRead, MobileUserUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MobileUserService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "hashed_password",
        "profile_image_object_key",
        "nearby_report_alert_location",
        "uuid",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "hashed_password",
        "profile_image_object_key",
        "nearby_report_alert_location",
        "uuid",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN = {
        "username": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "email": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "first_name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "last_name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "phone_number": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
        "tier_id": frozenset({
            FilterOp.EQ,
        }),
        "created_at": frozenset({
            FilterOp.LT,
            FilterOp.LTE,
            FilterOp.GT,
            FilterOp.GTE,
        }),
    }
    SEARCH_SORTABLE_COLUMNS = {
        "username",
        "email",
        "first_name",
        "last_name",
        "created_at",
    }

    def _is_unique_constraint_violation(self, error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_mobile_user(self, user_id: int, actor: Actor | None = None) -> MobileUser | None:
        query = (
            select(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
        )

        if actor is not None and actor.actor_type == ActorType.MOBILE_USER:
            query = query.where(MobileUser.id == actor.id)

        return (await self.db.execute(query)).scalar_one_or_none()

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
        user_id: int | None = None,
    ) -> PaginatedResponse[MobileUserRead]:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to search mobile users.")

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
                select(MobileUser)
                .where(
                    MobileUser.id == user_id,
                    MobileUser.is_deleted.is_(False),
                )
            )
        else:
            base_query = select(MobileUser).where(MobileUser.is_deleted.is_(False))

        engine = SearchEngine(
            db=self.db,
            model=MobileUser,
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
            serializer=MobileUserRead.model_validate,
        )

        return PaginatedResponse[MobileUserRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_mobile_users(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[MobileUserRead]:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to perform this action.")

        db_users = (
            await self.db.execute(
                select(MobileUser)
                .where(MobileUser.is_deleted.is_(False))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(MobileUser)
                .where(MobileUser.is_deleted.is_(False))
            )
        ).scalar_one()

        return PaginatedResponse[MobileUserRead](
            data=[MobileUserRead.model_validate(user) for user in db_users],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_mobile_user(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> MobileUserRead:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to view this user.")

        db_user = await self._get_mobile_user(user_id, actor)
        if db_user is None:
            raise NotFoundError("User not found.")

        return MobileUserRead.model_validate(db_user)

    async def update(
        self,
        *,
        actor: Actor,
        user_id: int,
        user_input: MobileUserUpdate,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to update this user.")

        db_user = await self._get_mobile_user(user_id, actor)
        if db_user is None:
            raise NotFoundError("User not found.")

        if user_input.profile_image_object_key is not None:
            if not is_object_exists(user_input.profile_image_object_key):
                raise InvalidInputError("The profile image may not have been uploaded correctly.")

        if user_input.nearby_report_alert_location is not None:
            wkb_location = from_shape(
                Point(
                    user_input.nearby_report_alert_location.longitude,
                    user_input.nearby_report_alert_location.latitude,
                ),
                srid=4326,
            )
            db_user.nearby_report_alert_location = wkb_location

        apply_partial_update(
            target=db_user,
            input=user_input,
            exclude={"nearby_report_alert_location"},
        )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_mobile_user_username_active"):
                raise InvalidInputError("A user with this username already exists.")

            if self._is_unique_constraint_violation(error, "uq_mobile_user_email_active"):
                raise InvalidInputError("A user with this email already exists.")

            if self._is_unique_constraint_violation(error, "uq_mobile_user_phone_number_active"):
                raise InvalidInputError("A user with this phone number already exists.")

            raise InvalidInputError("Unable to update the user.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the user."
            ) from error

    async def change_password(
        self,
        *,
        actor: Actor,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> None:
        if not (actor.is_superuser or actor.id == user_id):
            raise ForbiddenError("You do not have permission to change this user's password.")

        if actor.actor_type == ActorType.MOBILE_USER:
            user_id = actor.id

        hashed_password = (
            await self.db.execute(
                select(MobileUser.hashed_password)
                .where(
                    MobileUser.id == user_id,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if hashed_password is None:
            raise NotFoundError("User not found.")

        is_valid, _ = await verify_password(current_password, hashed_password)
        if not is_valid:
            raise InvalidInputError("Current password is incorrect.")

        statement = (
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(hashed_password=get_password_hash(new_password))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to change password. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to change password."
            ) from error

    async def update_tier(
        self,
        *,
        actor: Actor,
        user_id: int,
        tier_id: int | None,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update a user's tier.")

        if tier_id is not None:
            tier = await self._get_tier_by_id(tier_id)
            if tier is None:
                raise NotFoundError("Tier not found.")

        statement = (
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(tier_id=tier_id)
        )

        try:
            result = await self.db.execute(statement)
            if result.rowcount == 0:
                raise NotFoundError("User not found.")

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update tier. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update tier."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to delete a user.")

        statement = (
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(
                deleted_at=func.now(),
                is_deleted=True,
            )
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to delete the user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the user."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete a user.")

        statement = (
            delete(MobileUser)
            .where(MobileUser.id == user_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()
            raise InvalidInputError(
                "Unable to delete the user because it is referenced by other records."
            ) from error

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the user."
            ) from error

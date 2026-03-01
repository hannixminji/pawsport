import logging
from dataclasses import dataclass

from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.enums import AdminAccountStatus
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
from ..models._rbac_table import admin_user_permission, admin_user_role
from ..models.admin_permission import AdminPermission
from ..models.admin_role import AdminRole
from ..models.admin_user import AdminUser
from ..schemas.admin_user import (
    AdminUserCreate,
    AdminUserRead,
    AdminUserUpdate,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AdminUserService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS = frozenset({
        "id",
        "hashed_password",
        "profile_image_object_key",
        "last_active_at",
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
        "account_status": frozenset({
            FilterOp.EQ,
            FilterOp.IN,
        }),
        "is_superuser": frozenset({
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

    async def _get_admin_user_by_id(self, user_id: int) -> AdminUser | None:
        return (
            await self.db.execute(
                select(AdminUser)
                .where(
                    AdminUser.id == user_id,
                    AdminUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        user_input: AdminUserCreate,
    ) -> AdminUserRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to create an admin user.")

        if user_input.profile_image_object_key is not None:
            if not is_object_exists(user_input.profile_image_object_key):
                raise InvalidInputError("The profile image may not have been uploaded correctly.")

        user_model = AdminUser(
            **user_input.model_dump(exclude={"password"}),
            hashed_password=get_password_hash(user_input.password.get_secret_value())
        )
        self.db.add(user_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_user_username_active"):
                raise InvalidInputError("A user with this username already exists.")

            if self._is_unique_constraint_violation(error, "uq_admin_user_email_active"):
                raise InvalidInputError("A user with this email already exists.")

            if self._is_unique_constraint_violation(error, "uq_admin_user_phone_number_active"):
                raise InvalidInputError("A user with this phone number already exists.")

            raise InvalidInputError("Unable to create the admin user.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the admin user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the admin user."
            ) from error

        await self.db.refresh(user_model)
        return AdminUserRead.model_validate(user_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[AdminUserRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this search.")

        engine = SearchEngine(
            db=self.db,
            model=AdminUser,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = select(AdminUser).where(AdminUser.is_deleted.is_(False))
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=AdminUserRead.model_validate,
        )

        return PaginatedResponse[AdminUserRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_admin_users(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[AdminUserRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_users = (
            await self.db.execute(
                select(AdminUser)
                .where(AdminUser.is_deleted.is_(False))
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(AdminUser)
                .where(AdminUser.is_deleted.is_(False))
            )
        ).scalar_one()

        return PaginatedResponse[AdminUserRead](
            data=[AdminUserRead.model_validate(user) for user in db_users],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_admin_user(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> AdminUserRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        return AdminUserRead.model_validate(db_user)

    async def update(
        self,
        *,
        actor: Actor,
        user_id: int,
        user_input: AdminUserUpdate,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to update an admin user.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        if user_input.profile_image_object_key is not None:
            if not is_object_exists(user_input.profile_image_object_key):
                raise InvalidInputError("The profile image may not have been uploaded correctly.")

        apply_partial_update(target=db_user, input=user_input,)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_user_username_active"):
                raise InvalidInputError("A user with this username already exists.")

            if self._is_unique_constraint_violation(error, "uq_admin_user_email_active"):
                raise InvalidInputError("A user with this email already exists.")

            if self._is_unique_constraint_violation(error, "uq_admin_user_phone_number_active"):
                raise InvalidInputError("A user with this phone number already exists.")

            raise InvalidInputError("Unable to update the admin user.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the admin user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the admin user."
            ) from error

    async def soft_delete(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to delete an admin user.")

        statement = (
            update(AdminUser)
            .where(
                AdminUser.id == user_id,
                AdminUser.is_deleted.is_(False),
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
                "Failed to delete the admin user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete the admin user."
            ) from error

    async def bulk_soft_delete(
        self,
        *,
        actor: Actor,
        user_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to delete admin users.")

        if not user_ids:
            return

        statement = (
            update(AdminUser)
            .where(
                AdminUser.id == any_(list(user_ids)),
                AdminUser.is_deleted.is_(False),
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
                "Failed to delete admin users. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to delete admin users."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete an admin user.")

        statement = (
            delete(AdminUser)
            .where(AdminUser.id == user_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the admin user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the admin user."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        user_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete admin users.")

        if not user_ids:
            return

        statement = (
            delete(AdminUser)
            .where(AdminUser.id == any_(list(user_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete admin users. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete admin users."
            ) from error

    async def update_account_status(
        self,
        *,
        actor: Actor,
        user_id: int,
        account_status: AdminAccountStatus,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to update an admin user's account status.")

        statement = (
            update(AdminUser)
            .where(
                AdminUser.id == user_id,
                AdminUser.is_deleted.is_(False),
            )
            .values(account_status=account_status)
        )

        try:
            result = await self.db.execute(statement)
            if result.rowcount == 0:
                raise NotFoundError("Admin user not found.")

            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update account status. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update account status."
            ) from error

    async def change_password(
        self,
        *,
        actor: Actor,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> None:
        if not actor.is_superuser and actor.id != user_id:
            raise ForbiddenError("You do not have permission to change this user's password.")

        hashed_password = (
            await self.db.execute(
                select(AdminUser.hashed_password)
                .where(
                    AdminUser.id == user_id,
                    AdminUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if hashed_password is None:
            raise NotFoundError("Admin user not found.")

        is_valid, _ = await verify_password(current_password, hashed_password)
        if not is_valid:
            raise InvalidInputError("Current password is incorrect.")

        statement = (
            update(AdminUser)
            .where(
                AdminUser.id == user_id,
                AdminUser.is_deleted.is_(False),
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

    async def assign_roles(
        self,
        *,
        actor: Actor,
        user_id: int,
        role_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to assign roles to an admin user.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        roles = []
        if role_ids:
            roles = (
                await self.db.execute(
                    select(AdminRole)
                    .where(AdminRole.id == any_(list(role_ids)))
                )
            ).scalars().all()
            existing_ids = {role.id for role in roles}
            missing_ids = role_ids - existing_ids
            if missing_ids:
                raise InvalidInputError(f"Role IDs not found: {sorted(missing_ids)}")

        db_user.roles = roles

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to assign roles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to assign roles."
            ) from error

    async def remove_all_roles(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to remove roles from an admin user.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        statement = (
            delete(admin_user_role)
            .where(admin_user_role.c.admin_user_id == user_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to remove roles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to remove roles."
            ) from error

    async def assign_direct_permissions(
        self,
        *,
        actor: Actor,
        user_id: int,
        permission_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to assign direct permissions to an admin user.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        permissions = []
        if permission_ids:
            permissions = (
                await self.db.execute(
                    select(AdminPermission)
                    .where(AdminPermission.id == any_(list(permission_ids)))
                )
            ).scalars().all()
            existing_ids = {permission.id for permission in permissions}
            missing_ids = permission_ids - existing_ids
            if missing_ids:
                raise InvalidInputError(f"Permission IDs not found: {sorted(missing_ids)}")

        db_user.direct_permissions = permissions

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to assign direct permissions. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to assign direct permissions."
            ) from error

    async def remove_all_direct_permissions(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to remove direct permissions from an admin user.")

        db_user = await self._get_admin_user_by_id(user_id)
        if db_user is None:
            raise NotFoundError("Admin user not found.")

        statement = (
            delete(admin_user_permission)
            .where(admin_user_permission.c.admin_user_id == user_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to remove direct permissions. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to remove direct permissions."
            ) from error

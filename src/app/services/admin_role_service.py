import logging
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import any_, delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models._rbac_table import admin_role_permission
from ..models.admin_permission import AdminPermission
from ..models.admin_role import AdminRole
from ..schemas.admin_role import AdminRoleCreate, AdminRoleRead, AdminRoleReadWithPermissions, AdminRoleUpdate

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AdminRoleService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "description",
        "updated_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "name": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
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
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    async def _get_role_by_id(self, role_id: int) -> AdminRole | None:
        return (
            await self.db.execute(
                select(AdminRole)
                .where(AdminRole.id == role_id)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        role_input: AdminRoleCreate,
    ) -> AdminRoleRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to create an admin role.")

        role_model = AdminRole(**role_input.model_dump())
        self.db.add(role_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_role_name"):
                raise InvalidInputError("A role with this name already exists.")

            raise InvalidInputError("Unable to create the admin role.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the admin role. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the admin role."
            ) from error

        await self.db.refresh(role_model)
        return AdminRoleRead.model_validate(role_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[AdminRoleRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this search.")

        engine = SearchEngine(
            db=self.db,
            model=AdminRole,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = select(AdminRole)
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=AdminRoleRead.model_validate,
        )

        return PaginatedResponse[AdminRoleRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_roles(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[AdminRoleRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_roles = (
            await self.db.execute(
                select(AdminRole)
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(AdminRole)
            )
        ).scalar_one()

        return PaginatedResponse[AdminRoleRead](
            data=[AdminRoleRead.model_validate(role) for role in db_roles],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_role_with_permissions(
        self,
        *,
        actor: Actor,
        role_id: int,
    ) -> AdminRoleReadWithPermissions:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_role = (
            await self.db.execute(
                select(AdminRole)
                .options(selectinload(AdminRole.permissions))
                .where(AdminRole.id == role_id)
            )
        ).scalar_one_or_none()
        if db_role is None:
            raise NotFoundError("Admin role not found.")

        return AdminRoleReadWithPermissions.model_validate(db_role)

    async def get_role(
        self,
        *,
        actor: Actor,
        role_id: int,
    ) -> AdminRoleRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_role = await self._get_role_by_id(role_id)
        if db_role is None:
            raise NotFoundError("Admin role not found.")

        return AdminRoleRead.model_validate(db_role)

    async def update(
        self,
        *,
        actor: Actor,
        role_id: int,
        role_input: AdminRoleUpdate,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to update an admin role.")

        db_role = await self._get_role_by_id(role_id)
        if db_role is None:
            raise NotFoundError("Admin role not found.")

        apply_partial_update(target=db_role, input=role_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_role_name"):
                raise InvalidInputError("A role with this name already exists.")

            raise InvalidInputError("Unable to update the admin role.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the admin role. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the admin role."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        role_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete an admin role.")

        statement = (
            delete(AdminRole)
            .where(AdminRole.id == role_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the admin role. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the admin role."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        role_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete admin roles.")

        if not role_ids:
            return

        statement = (
            delete(AdminRole)
            .where(AdminRole.id == any_(list(role_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete admin roles. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete admin roles."
            ) from error

    async def assign_permissions(
        self,
        *,
        actor: Actor,
        role_id: int,
        permission_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to assign permissions to a role.")

        db_role = await self._get_role_by_id(role_id)
        if db_role is None:
            raise NotFoundError("Admin role not found.")

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

        db_role.permissions = permissions

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to assign permissions. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to assign permissions."
            ) from error

    async def remove_all_permissions(
        self,
        *,
        actor: Actor,
        role_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to remove permissions from a role.")

        db_role = await self._get_role_by_id(role_id)
        if db_role is None:
            raise NotFoundError("Admin role not found.")

        statement = (
            delete(admin_role_permission)
            .where(admin_role_permission.c.admin_role_id == role_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to remove permissions. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to remove permissions."
            ) from error

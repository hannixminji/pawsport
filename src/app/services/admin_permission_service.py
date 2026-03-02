import logging
from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy import any_, delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.admin_permission import AdminPermission
from ..schemas.admin_permission import (
    AdminPermissionCreate,
    AdminPermissionRead,
    AdminPermissionUpdate,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class AdminPermissionService:
    db: AsyncSession

    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "description",
        "bit_index",
        "updated_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
        "key": frozenset({
            FilterOp.EQ,
            FilterOp.ILIKE,
        }),
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

    async def _get_permission_by_id(self, permission_id: int) -> AdminPermission | None:
        return (
            await self.db.execute(
                select(AdminPermission)
                .where(AdminPermission.id == permission_id)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        actor: Actor,
        permission_input: AdminPermissionCreate,
    ) -> AdminPermissionRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to create an admin permission.")

        permission_model = AdminPermission(**permission_input.model_dump())
        self.db.add(permission_model)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_permission_key"):
                raise InvalidInputError("A permission with this key already exists.")

            raise InvalidInputError("Unable to create the admin permission.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the admin permission. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the admin permission."
            ) from error

        await self.db.refresh(permission_model)
        return AdminPermissionRead.model_validate(permission_model)

    async def search(
        self,
        *,
        actor: Actor,
        search_request: SearchRequest,
    ) -> PaginatedResponse[AdminPermissionRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this search.")

        engine = SearchEngine(
            db=self.db,
            model=AdminPermission,
            blacklisted_columns=self.ADMIN_SEARCH_BLACKLIST_COLUMNS,
            allowed_ops=self.ALLOWED_FILTER_OPERATORS_BY_COLUMN,
            column_order_map=None,
            sortable_columns=self.SEARCH_SORTABLE_COLUMNS,
            max_in_list_size=100,
            max_depth=1,
        )

        base_query = select(AdminPermission)
        result = await engine.search(
            base_query=base_query,
            values=search_request,
            serializer=AdminPermissionRead.model_validate,
        )

        return PaginatedResponse[AdminPermissionRead](
            data=result.data,
            total_count=result.total_count,
            has_more=(result.page * result.items_per_page) < result.total_count,
            page=result.page,
            items_per_page=result.items_per_page,
        )

    async def get_all_permissions(
        self,
        *,
        actor: Actor,
        page: int,
        items_per_page: int,
    ) -> PaginatedResponse[AdminPermissionRead]:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_permissions = (
            await self.db.execute(
                select(AdminPermission)
                .offset(compute_offset(page, items_per_page))
                .limit(items_per_page)
            )
        ).scalars().all()

        total_count = (
            await self.db.execute(
                select(func.count())
                .select_from(AdminPermission)
            )
        ).scalar_one()

        return PaginatedResponse[AdminPermissionRead](
            data=[AdminPermissionRead.model_validate(permission) for permission in db_permissions],
            total_count=total_count,
            has_more=(page * items_per_page) < total_count,
            page=page,
            items_per_page=items_per_page,
        )

    async def get_permission(
        self,
        *,
        actor: Actor,
        permission_id: int,
    ) -> AdminPermissionRead:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to perform this action.")

        db_permission = await self._get_permission_by_id(permission_id)
        if db_permission is None:
            raise NotFoundError("Admin permission not found.")

        return AdminPermissionRead.model_validate(db_permission)

    async def update(
        self,
        *,
        actor: Actor,
        permission_id: int,
        permission_input: AdminPermissionUpdate,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to update an admin permission.")

        db_permission = await self._get_permission_by_id(permission_id)
        if db_permission is None:
            raise NotFoundError("Admin permission not found.")

        apply_partial_update(target=db_permission, input=permission_input)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_admin_permission_key"):
                raise InvalidInputError("A permission with this key already exists.")

            raise InvalidInputError("Unable to update the admin permission.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the admin permission. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the admin permission."
            ) from error

    async def hard_delete(
        self,
        *,
        actor: Actor,
        permission_id: int,
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete an admin permission.")

        statement = (
            delete(AdminPermission)
            .where(AdminPermission.id == permission_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete the admin permission. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete the admin permission."
            ) from error

    async def bulk_hard_delete(
        self,
        *,
        actor: Actor,
        permission_ids: set[int],
    ) -> None:
        if not actor.is_superuser:
            raise ForbiddenError("Superuser privileges are required to permanently delete admin permissions.")

        if not permission_ids:
            return

        statement = (
            delete(AdminPermission)
            .where(AdminPermission.id == any_(list(permission_ids)))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to permanently delete admin permissions. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to permanently delete admin permissions."
            ) from error

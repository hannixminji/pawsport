import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from fastapi.templating import Jinja2Templates
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import any_, delete, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..core.config import settings
from ..core.enums import ActorType, AuthProvider, MobileUserAccountStatus, UserTokenType
from ..core.exceptions.authorization_exceptions import ForbiddenError
from ..core.exceptions.db_exceptions import NonTransientDatabaseError, TransientDatabaseError
from ..core.exceptions.domain_exceptions import InvalidInputError, NotFoundError
from ..core.exceptions.http_exceptions import DuplicateValueException, UnauthorizedException
from ..core.schemas import Actor, PaginatedResponse
from ..core.search_engine.engine import SearchEngine
from ..core.search_engine.enums import FilterOp
from ..core.search_engine.schemas import SearchRequest
from ..core.security import (
    create_access_token,
    create_refresh_session,
    generate_refresh_token,
    get_password_hash,
    revoke_refresh_session,
    rotate_refresh_token,
    verify_firebase_token,
    verify_password,
)
from ..core.utils import queue
from ..core.utils.google_cloud_storage import is_object_exists
from ..core.utils.pagination import compute_offset
from ..core.utils.update import apply_partial_update
from ..models.mobile_user import MobileUser
from ..models.tier import Tier
from ..models.user_linked_account import UserLinkedAccount
from ..schemas.mobile_user import (
    MobileUserAccountStatusUpdate,
    MobileUserCreate,
    MobileUserEmailPasswordLogin,
    MobileUserEmailPasswordRegister,
    MobileUserRead,
    MobileUserUpdate,
)
from ..schemas.token import TokenResponse
from .mobile_user_token_service import MobileUserTokenService

LOGGER = logging.getLogger(__name__)

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "core" / "templates"))

_ACCOUNT_STATUS_ERRORS: dict[MobileUserAccountStatus, str] = {
    MobileUserAccountStatus.SUSPENDED: "Your account has been suspended. Please contact support.",
    MobileUserAccountStatus.BANNED: "Your account has been banned.",
    MobileUserAccountStatus.DEACTIVATED: "Your account has been deactivated. Please contact support.",
}

_GUEST_ACCOUNT_STATUS_ERRORS: dict[MobileUserAccountStatus, str] = {
    MobileUserAccountStatus.SUSPENDED: "Your guest session has been suspended.",
    MobileUserAccountStatus.BANNED: "Your guest session has been banned.",
    MobileUserAccountStatus.DEACTIVATED: "Your guest session is no longer active.",
}


@dataclass(slots=True)
class MobileUserService:
    db: AsyncSession

    MOBILE_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "hashed_password",
        "profile_image_object_key",
        "nearby_report_alert_location",
        "uuid",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ADMIN_SEARCH_BLACKLIST_COLUMNS: ClassVar[frozenset[str]] = frozenset({
        "id",
        "hashed_password",
        "profile_image_object_key",
        "nearby_report_alert_location",
        "uuid",
        "is_deleted",
        "updated_at",
        "deleted_at",
    })
    ALLOWED_FILTER_OPERATORS_BY_COLUMN: ClassVar[dict] = {
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
    SEARCH_SORTABLE_COLUMNS: ClassVar[set[str]] = {
        "username",
        "email",
        "first_name",
        "last_name",
        "created_at",
    }

    @staticmethod
    def _is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
        original_exception = getattr(error, "orig", None)
        if original_exception is None:
            return False

        return constraint_name in str(original_exception)

    @staticmethod
    def _assert_account_active(user: MobileUser) -> None:
        errors = _GUEST_ACCOUNT_STATUS_ERRORS if user.is_anonymous else _ACCOUNT_STATUS_ERRORS
        message = errors.get(user.account_status)
        if message:
            raise UnauthorizedException(message)

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

    async def _get_tier_by_id(self, tier_id: int) -> Tier | None:
        return (
            await self.db.execute(
                select(Tier)
                .where(Tier.id == tier_id)
            )
        ).scalar_one_or_none()

    async def _get_tier_id_by_name(self, name: str) -> int | None:
        tier = (
            await self.db.execute(
                select(Tier)
                .where(Tier.name == name)
            )
        ).scalar_one_or_none()
        return tier.id if tier else None

    async def _enqueue_email(
        self,
        *,
        to_email: str,
        subject: str,
        html: str,
    ) -> None:
        try:
            await queue.pool.enqueue_job(
                "send_email_task",
                to_email=to_email,
                subject=subject,
                html=html,
            )

        except Exception as error:
            LOGGER.error(f"Failed to enqueue send_email_task for {to_email}: {error}")

    def render_template(self, template_name: str, **context) -> str:
        return TEMPLATES.get_template(template_name).render(**context)

    async def register(
        self,
        *,
        payload: MobileUserEmailPasswordRegister,
    ) -> TokenResponse:
        existing_user = (
            await self.db.execute(
                select(MobileUser)
                .where(
                    MobileUser.email == payload.email,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing_user is not None:
            raise DuplicateValueException("A user with this email already exists.")

        free_tier_id = await self._get_tier_id_by_name(settings.FREE_TIER_NAME)

        base_username = f"user{uuid.uuid4().hex[:10]}"
        new_user = MobileUser(
            username=base_username,
            tier_id=free_tier_id,
            email=payload.email,
            is_email_verified=False,
        )
        self.db.add(new_user)
        await self.db.flush()

        new_linked_account = UserLinkedAccount(
            mobile_user_id=new_user.id,
            provider=AuthProvider.EMAIL,
            provider_user_id=payload.email,
            provider_email=payload.email,
            hashed_password=get_password_hash(payload.password.get_secret_value()),
        )
        self.db.add(new_linked_account)
        await self.db.flush()

        access_token = await create_access_token(data={"sub": str(new_user.id)})
        opaque_token, token_hash = generate_refresh_token()
        await create_refresh_session(self.db, new_user.id, token_hash)

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_mobile_user_email_active"):
                raise DuplicateValueException("A user with this email already exists.")

            if self._is_unique_constraint_violation(error, "uq_mobile_user_username_active"):
                raise DuplicateValueException("Username conflict. Please try again.")

            raise DuplicateValueException("Unable to complete registration. Please try again.")

        except OperationalError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create account. Please try again later.")

        except SQLAlchemyError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create account.")

        await self.db.refresh(new_user)

        await self.send_verification_email(
            actor=Actor(
                id=new_user.id,
                actor_type=ActorType.MOBILE_USER,
                is_superuser=False,
                is_anonymous=False,
                role_ids=None,
                request_id=str(uuid.uuid4()),
                ip_address=None,
                user_agent=None,
            ),
            user_id=new_user.id,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=opaque_token,
            token_type="bearer",
            user=MobileUserRead.model_validate(new_user),
        )

    async def login(
        self,
        *,
        payload: MobileUserEmailPasswordLogin,
    ) -> TokenResponse:
        linked_account = (
            await self.db.execute(
                select(UserLinkedAccount)
                .options(selectinload(UserLinkedAccount.mobile_user))
                .where(
                    UserLinkedAccount.provider == AuthProvider.EMAIL,
                    UserLinkedAccount.provider_email == payload.email,
                    UserLinkedAccount.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

        if linked_account is None or linked_account.mobile_user is None or linked_account.mobile_user.is_deleted:
            raise UnauthorizedException("Invalid email or password.")

        is_valid, _ = await verify_password(
            payload.password.get_secret_value(),
            linked_account.hashed_password,
        )
        if not is_valid:
            raise UnauthorizedException("Invalid email or password.")

        self._assert_account_active(linked_account.mobile_user)

        access_token = await create_access_token(data={"sub": str(linked_account.mobile_user.id)})
        opaque_token, token_hash = generate_refresh_token()
        await create_refresh_session(self.db, linked_account.mobile_user.id, token_hash)

        try:
            await self.db.commit()

        except OperationalError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create session. Please try again later.")

        except SQLAlchemyError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create session.")

        return TokenResponse(
            access_token=access_token,
            refresh_token=opaque_token,
            token_type="bearer",
            user=MobileUserRead.model_validate(linked_account.mobile_user),
        )

    async def login_or_signup_google(
        self,
        *,
        token: str,
    ) -> MobileUserRead:
        try:
            token_data = verify_firebase_token(token)
        except ValueError as error:
            raise UnauthorizedException(str(error))
        except Exception as error:
            raise UnauthorizedException(str(error))

        sign_in_provider = token_data.get("firebase", {}).get("sign_in_provider")
        identities = token_data.get("firebase", {}).get("identities", {})
        provider_ids = identities.get(sign_in_provider)
        if not provider_ids:
            raise UnauthorizedException("Missing provider user ID in token")
        provider_user_id = provider_ids[0]

        email = token_data.get("email")
        if not email:
            raise UnauthorizedException("Email not provided in token")

        async def get_linked_account() -> UserLinkedAccount | None:
            return (
                await self.db.execute(
                    select(UserLinkedAccount)
                    .options(selectinload(UserLinkedAccount.mobile_user))
                    .where(
                        UserLinkedAccount.provider == sign_in_provider,
                        UserLinkedAccount.provider_user_id == provider_user_id,
                        UserLinkedAccount.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()

        def linked_account_user_is_valid(linked_account: UserLinkedAccount | None) -> bool:
            return bool(
                linked_account
                and linked_account.mobile_user
                and not linked_account.mobile_user.is_deleted
            )

        linked_account = await get_linked_account()
        if linked_account_user_is_valid(linked_account):
            self._assert_account_active(linked_account.mobile_user)
            return MobileUserRead.model_validate(linked_account.mobile_user)

        mobile_user = (
            await self.db.execute(
                select(MobileUser)
                .where(
                    MobileUser.email == email,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

        if mobile_user:
            if not mobile_user.is_email_verified:
                raise UnauthorizedException(
                    "An account with this email exists but has not been verified. Please verify your email first."
                )
            self._assert_account_active(mobile_user)
            new_linked_account = UserLinkedAccount(
                mobile_user_id=mobile_user.id,
                provider=sign_in_provider,
                provider_user_id=provider_user_id,
                provider_email=email,
            )
            self.db.add(new_linked_account)

            try:
                await self.db.commit()
            except IntegrityError as error:
                await self.db.rollback()

                if self._is_unique_constraint_violation(
                    error,
                    "uq_user_linked_account_provider_provider_user_id_active"
                ):
                    linked_account = await get_linked_account()
                    if linked_account_user_is_valid(linked_account):
                        self._assert_account_active(linked_account.mobile_user)
                        return MobileUserRead.model_validate(linked_account.mobile_user)

                raise DuplicateValueException("Linked account creation failed. Please try again.")

            await self.db.refresh(mobile_user)
            return MobileUserRead.model_validate(mobile_user)

        free_tier_id = await self._get_tier_id_by_name(settings.FREE_TIER_NAME)

        base_username = f"user{uuid.uuid4().hex[:10]}"
        new_user = MobileUser(
            username=base_username,
            tier_id=free_tier_id,
            email=email,
        )
        self.db.add(new_user)
        await self.db.flush()

        new_linked_account = UserLinkedAccount(
            mobile_user_id=new_user.id,
            provider=sign_in_provider,
            provider_user_id=provider_user_id,
            provider_email=email,
        )
        self.db.add(new_linked_account)

        try:
            await self.db.commit()
        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(
                error,
                "uq_user_linked_account_provider_provider_user_id_active"
            ):
                linked_account = await get_linked_account()
                if linked_account_user_is_valid(linked_account):
                    self._assert_account_active(linked_account.mobile_user)
                    return MobileUserRead.model_validate(linked_account.mobile_user)
                raise UnauthorizedException("Authentication failed due to conflicting account.")

            if self._is_unique_constraint_violation(
                error,
                "uq_mobile_user_email_active"
            ):
                existing_user = (
                    await self.db.execute(
                        select(MobileUser)
                        .where(
                            MobileUser.email == email,
                            MobileUser.is_deleted.is_(False)
                        )
                    )
                ).scalar_one_or_none()
                if existing_user:
                    self._assert_account_active(existing_user)
                    retry_linked = UserLinkedAccount(
                        mobile_user_id=existing_user.id,
                        provider=sign_in_provider,
                        provider_user_id=provider_user_id,
                        provider_email=email
                    )
                    self.db.add(retry_linked)
                    try:
                        await self.db.commit()
                    except IntegrityError as inner_error:
                        await self.db.rollback()

                        if self._is_unique_constraint_violation(
                            inner_error,
                            "uq_user_linked_account_provider_provider_user_id_active"
                        ):
                            linked_account = await get_linked_account()
                            if linked_account_user_is_valid(linked_account):
                                self._assert_account_active(linked_account.mobile_user)
                                return MobileUserRead.model_validate(linked_account.mobile_user)

                        raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

                    await self.db.refresh(existing_user)
                    return MobileUserRead.model_validate(existing_user)

            if self._is_unique_constraint_violation(
                error,
                "uq_mobile_user_username_active"
            ):
                raise DuplicateValueException("Username conflict. Please try again.")

            raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

        await self.db.refresh(new_user)
        return MobileUserRead.model_validate(new_user)

    async def guest_login(self) -> TokenResponse:
        guest_uid = str(uuid.uuid4())

        guest_tier_id = await self._get_tier_id_by_name(settings.GUEST_TIER_NAME)

        new_user = MobileUser(
            username=f"guest{uuid.uuid4().hex[:10]}",
            tier_id=guest_tier_id,
            is_anonymous=True,
        )
        self.db.add(new_user)
        await self.db.flush()

        new_linked_account = UserLinkedAccount(
            mobile_user_id=new_user.id,
            provider=AuthProvider.ANONYMOUS,
            provider_user_id=guest_uid,
        )
        self.db.add(new_linked_account)
        await self.db.flush()

        access_token = await create_access_token(data={"sub": str(new_user.id)})
        opaque_token, token_hash = generate_refresh_token()
        await create_refresh_session(self.db, new_user.id, token_hash)

        try:
            await self.db.commit()

        except IntegrityError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create guest session. Please try again.")

        except OperationalError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create guest session. Please try again later.")

        except SQLAlchemyError:
            await self.db.rollback()

            raise UnauthorizedException("Failed to create guest session.")

        await self.db.refresh(new_user)

        return TokenResponse(
            access_token=access_token,
            refresh_token=opaque_token,
            token_type="bearer",
            user=MobileUserRead.model_validate(new_user),
        )

    async def refresh_token(
        self,
        *,
        refresh_token: str,
    ) -> TokenResponse:
        result = await rotate_refresh_token(refresh_token, self.db)
        if result is None:
            raise UnauthorizedException("Invalid or expired refresh token.")

        new_access_token, new_refresh_token, user_id = result
        await self.db.commit()

        mobile_user = (
            await self.db.execute(
                select(MobileUser)
                .where(
                    MobileUser.id == user_id,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if mobile_user is None:
            raise UnauthorizedException("User not found.")

        self._assert_account_active(mobile_user)

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            user=MobileUserRead.model_validate(mobile_user),
        )

    async def logout(
        self,
        *,
        refresh_token: str,
    ) -> dict[str, str]:
        await revoke_refresh_session(refresh_token, self.db)
        await self.db.commit()
        return {"message": "Logged out successfully"}

    async def forgot_password(
        self,
        *,
        email: str,
    ) -> None:
        db_user = (
            await self.db.execute(
                select(MobileUser)
                .where(
                    MobileUser.email == email,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()

        if db_user is None or not db_user.is_email_verified:
            return

        token_service = MobileUserTokenService(db=self.db)
        raw_token = await token_service.create_token(
            mobile_user_id=db_user.id,
            token_type=UserTokenType.PASSWORD_RESET,
        )

        html = TEMPLATES.get_template("password_reset.html").render(
            reset_url=f"{settings.APP_URL}/api/v1/auth/reset-password?token={raw_token}",
            expire_minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
        )

        await self._enqueue_email(
            to_email=db_user.email,
            subject="Reset your password",
            html=html,
        )

    async def reset_password(
        self,
        *,
        raw_token: str,
        new_password: str,
    ) -> None:
        token_service = MobileUserTokenService(db=self.db)
        db_token = await token_service.verify_token(
            raw_token=raw_token,
            token_type=UserTokenType.PASSWORD_RESET,
        )

        user_id = db_token.mobile_user_id

        db_user = await self._get_mobile_user(user_id)
        if db_user is None:
            raise NotFoundError("User not found.")

        await token_service.consume_token(token_id=db_token.id)

        statement = (
            update(UserLinkedAccount)
            .where(
                UserLinkedAccount.mobile_user_id == user_id,
                UserLinkedAccount.provider == AuthProvider.EMAIL,
                UserLinkedAccount.is_deleted.is_(False),
            )
            .values(hashed_password=get_password_hash(new_password))
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to reset password. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to reset password."
            ) from error

    async def create(
        self,
        *,
        actor: Actor,
        user_input: MobileUserCreate,
    ) -> MobileUserRead:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to create a mobile user.")

        if user_input.profile_image_object_key is not None:
            if not is_object_exists(user_input.profile_image_object_key):
                raise InvalidInputError("The profile image may not have been uploaded correctly.")

        user_model = MobileUser(**user_input.model_dump())

        self.db.add(user_model)

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

            raise InvalidInputError("Unable to create the mobile user.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to create the mobile user. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to create the mobile user."
            ) from error

        await self.db.refresh(user_model)
        return MobileUserRead.model_validate(user_model)

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
            max_depth=5,
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

    async def send_verification_email(
        self,
        *,
        actor: Actor,
        user_id: int,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to perform this action.")

        db_user = await self._get_mobile_user(user_id, actor)
        if db_user is None:
            raise NotFoundError("User not found.")

        if db_user.is_email_verified:
            raise InvalidInputError("Email is already verified.")

        if db_user.email is None:
            raise InvalidInputError("No email address found for this user.")

        token_service = MobileUserTokenService(db=self.db)
        raw_token = await token_service.create_token(
            mobile_user_id=user_id,
            token_type=UserTokenType.EMAIL_VERIFICATION,
        )

        html = TEMPLATES.get_template("email_verification.html").render(
            verification_url=f"{settings.APP_URL}/api/v1/mobile-users/verify-email?token={raw_token}",
            expire_minutes=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_MINUTES,
        )

        await self._enqueue_email(
            to_email=db_user.email,
            subject="Verify your email address",
            html=html,
        )

    async def verify_email(
        self,
        *,
        raw_token: str,
    ) -> None:
        token_service = MobileUserTokenService(db=self.db)
        db_token = await token_service.verify_token(
            raw_token=raw_token,
            token_type=UserTokenType.EMAIL_VERIFICATION,
        )

        user_id = db_token.mobile_user_id

        db_user = await self._get_mobile_user(user_id)
        if db_user is None:
            raise NotFoundError("User not found.")

        if db_user.is_email_verified:
            raise InvalidInputError("Email is already verified.")

        await token_service.consume_token(token_id=db_token.id)

        await self.db.execute(
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(is_email_verified=True)
        )

        try:
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to verify email. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to verify email."
            ) from error

    async def request_email_change(
        self,
        *,
        actor: Actor,
        user_id: int,
        new_email: str,
    ) -> None:
        if actor.actor_type not in (ActorType.MOBILE_USER, ActorType.ADMIN_USER):
            raise ForbiddenError("You do not have permission to change this user's email.")

        db_user = await self._get_mobile_user(user_id, actor)
        if db_user is None:
            raise NotFoundError("User not found.")

        if db_user.email == new_email:
            raise InvalidInputError("New email must be different from your current email.")

        existing = (
            await self.db.execute(
                select(MobileUser)
                .where(
                    MobileUser.email == new_email,
                    MobileUser.id != user_id,
                    MobileUser.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise InvalidInputError("A user with this email already exists.")

        token_service = MobileUserTokenService(db=self.db)
        raw_token = await token_service.create_token(
            mobile_user_id=user_id,
            token_type=UserTokenType.EMAIL_CHANGE,
            payload={"new_email": new_email},
        )

        html = TEMPLATES.get_template("email_change.html").render(
            verification_url=f"{settings.APP_URL}/api/v1/mobile-users/verify-email-change?token={raw_token}",
            expire_minutes=settings.EMAIL_CHANGE_TOKEN_EXPIRE_MINUTES,
        )

        await self._enqueue_email(
            to_email=new_email,
            subject="Confirm your new email address",
            html=html,
        )

    async def verify_email_change(
        self,
        *,
        raw_token: str,
    ) -> None:
        token_service = MobileUserTokenService(db=self.db)
        db_token = await token_service.verify_token(
            raw_token=raw_token,
            token_type=UserTokenType.EMAIL_CHANGE,
        )

        user_id = db_token.mobile_user_id

        db_user = await self._get_mobile_user(user_id)
        if db_user is None:
            raise NotFoundError("User not found.")

        new_email = db_token.payload_json["new_email"]

        await token_service.consume_token(token_id=db_token.id)

        await self.db.execute(
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(email=new_email)
        )

        await self.db.execute(
            update(UserLinkedAccount)
            .where(
                UserLinkedAccount.mobile_user_id == user_id,
                UserLinkedAccount.provider == AuthProvider.EMAIL,
                UserLinkedAccount.is_deleted.is_(False),
            )
            .values(provider_email=new_email)
        )

        try:
            await self.db.commit()

        except IntegrityError as error:
            await self.db.rollback()

            if self._is_unique_constraint_violation(error, "uq_mobile_user_email_active"):
                raise InvalidInputError("A user with this email already exists.")

            raise InvalidInputError("Unable to update the email.")

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update the email. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update the email."
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

        linked_account = (
            await self.db.execute(
                select(UserLinkedAccount)
                .where(
                    UserLinkedAccount.mobile_user_id == user_id,
                    UserLinkedAccount.provider == AuthProvider.EMAIL,
                    UserLinkedAccount.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if linked_account is None:
            raise NotFoundError("No email/password account found for this user.")

        is_valid, _ = await verify_password(current_password, linked_account.hashed_password)
        if not is_valid:
            raise InvalidInputError("Current password is incorrect.")

        statement = (
            update(UserLinkedAccount)
            .where(
                UserLinkedAccount.mobile_user_id == user_id,
                UserLinkedAccount.provider == AuthProvider.EMAIL,
                UserLinkedAccount.is_deleted.is_(False),
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

    async def bulk_update_tier(
        self,
        *,
        actor: Actor,
        user_ids: set[int],
        tier_id: int,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update user tiers.")

        tier = await self._get_tier_by_id(tier_id)
        if tier is None:
            raise NotFoundError("Tier not found.")

        statement = (
            update(MobileUser)
            .where(
                MobileUser.id == any_(list(user_ids)),
                MobileUser.is_deleted.is_(False),
            )
            .values(tier_id=tier_id)
        )

        try:
            await self.db.execute(statement)
            await self.db.commit()

        except OperationalError as error:
            await self.db.rollback()

            raise TransientDatabaseError(
                "Failed to update user tiers. Please try again later."
            ) from error

        except SQLAlchemyError as error:
            await self.db.rollback()

            raise NonTransientDatabaseError(
                "Failed to update user tiers."
            ) from error

    async def update_account_status(
        self,
        *,
        actor: Actor,
        user_id: int,
        user_input: MobileUserAccountStatusUpdate,
    ) -> None:
        if actor.actor_type != ActorType.ADMIN_USER:
            raise ForbiddenError("Admin privileges are required to update a user's account status.")

        statement = (
            update(MobileUser)
            .where(
                MobileUser.id == user_id,
                MobileUser.is_deleted.is_(False),
            )
            .values(account_status=user_input.account_status)
        )

        try:
            result = await self.db.execute(statement)
            if result.rowcount == 0:
                raise NotFoundError("User not found.")

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
            result = await self.db.execute(statement)
            if result.rowcount == 0:
                raise NotFoundError("User not found.")

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

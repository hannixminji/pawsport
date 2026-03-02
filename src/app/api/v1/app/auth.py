import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db.database import async_get_db
from app.core.exceptions.http_exceptions import DuplicateValueException, UnauthorizedException
from app.core.security import security, verify_firebase_token
from app.models.mobile_user import MobileUser
from app.models.user_linked_account import UserLinkedAccount
from app.schemas.mobile_user import MobileUserRead

router = APIRouter(tags=["login or signup"])


def is_unique_constraint_violation(error: IntegrityError, constraint_name: str) -> bool:
    original_exception = getattr(error, "orig", None)
    if original_exception is None:
        return False

    return constraint_name in str(original_exception)


@router.post("/login_or_signup", response_model=MobileUserRead)
async def login_or_signup(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> MobileUserRead:
    token = credentials.credentials

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
            await db.execute(
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
        return MobileUserRead.model_validate(linked_account.mobile_user)

    mobile_user = (
        await db.execute(
            select(MobileUser)
            .where(
                MobileUser.email == email,
                MobileUser.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()

    if mobile_user:
        new_linked_account = UserLinkedAccount(
            mobile_user_id=mobile_user.id,
            provider=sign_in_provider,
            provider_user_id=provider_user_id,
            provider_email=email,
        )
        db.add(new_linked_account)

        try:
            await db.commit()
        except IntegrityError as error:
            await db.rollback()

            if is_unique_constraint_violation(
                error,
                "uq_user_linked_account_provider_provider_user_id_active"
            ):
                linked_account = await get_linked_account()
                if linked_account_user_is_valid(linked_account):
                    return MobileUserRead.model_validate(linked_account.mobile_user)

            raise DuplicateValueException("Linked account creation failed. Please try again.")

        await db.refresh(mobile_user)
        return MobileUserRead.model_validate(mobile_user)

    base_username = f"user{uuid.uuid4().hex[:10]}"
    new_user = MobileUser(
        username=base_username,
        email=email,
    )

    new_linked_account = UserLinkedAccount(
        provider=sign_in_provider,
        provider_user_id=provider_user_id,
        provider_email=email,
    )

    new_user.linked_accounts.append(new_linked_account)
    db.add(new_user)

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()

        if is_unique_constraint_violation(
            error,
            "uq_user_linked_account_provider_provider_user_id_active"
        ):
            linked_account = await get_linked_account()
            if linked_account_user_is_valid(linked_account):
                return MobileUserRead.model_validate(linked_account.mobile_user)
            raise UnauthorizedException("Authentication failed due to conflicting account.")

        if is_unique_constraint_violation(
            error,
            "uq_mobile_user_email_active"
        ):
            existing_user = (
                await db.execute(
                    select(MobileUser)
                    .where(
                        MobileUser.email == email,
                        MobileUser.is_deleted.is_(False)
                    )
                )
            ).scalar_one_or_none()
            if existing_user:
                retry_linked = UserLinkedAccount(
                    mobile_user_id=existing_user.id,
                    provider=sign_in_provider,
                    provider_user_id=provider_user_id,
                    provider_email=email
                )
                db.add(retry_linked)
                try:
                    await db.commit()
                except IntegrityError as inner_error:
                    await db.rollback()

                    if is_unique_constraint_violation(
                        inner_error,
                        "uq_user_linked_account_provider_provider_user_id_active"
                    ):
                        linked_account = await get_linked_account()
                        if linked_account_user_is_valid(linked_account):
                            return MobileUserRead.model_validate(linked_account.mobile_user)

                    raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

                await db.refresh(existing_user)
                return MobileUserRead.model_validate(existing_user)

        if is_unique_constraint_violation(
            error,
            "uq_mobile_user_username_active"
        ):
            raise DuplicateValueException("Username conflict. Please try again.")

        raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

    await db.refresh(new_user)
    return MobileUserRead.model_validate(new_user)

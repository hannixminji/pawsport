import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...core.db.database import async_get_db
from ...core.exceptions.http_exceptions import DuplicateValueException, UnauthorizedException
from ...core.security import security, verify_firebase_token
from ...models.user import User
from ...models.user_linked_account import UserLinkedAccount
from ...schemas.user import UserRead

router = APIRouter(tags=["login or signup"])


@router.get("/login_or_signup", response_model=UserRead)
async def login_or_signup(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(async_get_db)]
) -> UserRead:
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
    provider_user_id = provider_ids[0]

    email = token_data.get("email")

    linked_account = (
        await db.execute(
            select(UserLinkedAccount)
            .options(selectinload(UserLinkedAccount.user))
            .where(
                UserLinkedAccount.provider == sign_in_provider,
                UserLinkedAccount.provider_user_id == provider_user_id,
                ~UserLinkedAccount.is_deleted
            )
        )
    ).scalar_one_or_none()

    if linked_account and linked_account.user and not linked_account.user.is_deleted:
        return UserRead.model_validate(linked_account.user)

    user = (
        await db.execute(
            select(User)
            .where(
                User.email == email,
                ~User.is_deleted
            )
        )
    ).scalar_one_or_none()

    if user:
        linked_account_model = UserLinkedAccount(
            user_id=user.id,
            provider=sign_in_provider,
            provider_user_id=provider_user_id
        )

        db.add(linked_account_model)

        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()

            linked_account = (
                await db.execute(
                    select(UserLinkedAccount)
                    .options(selectinload(UserLinkedAccount.user))
                    .where(
                        UserLinkedAccount.provider == sign_in_provider,
                        UserLinkedAccount.provider_user_id == provider_user_id,
                        ~UserLinkedAccount.is_deleted
                    )
                )
            ).scalar_one_or_none()

            if not linked_account or not linked_account.user or linked_account.user.is_deleted:
                raise DuplicateValueException("Linked account or user invalid.")

            return UserRead.model_validate(linked_account.user)

        await db.refresh(user)

        return UserRead.model_validate(user)

    user = User(
        username=f"user{uuid.uuid4().hex[:10]}",
        email=email
    )

    db.add(user)
    await db.flush()

    linked_account_model = UserLinkedAccount(
        user_id=user.id,
        provider=sign_in_provider,
        provider_user_id=provider_user_id
    )

    db.add(linked_account_model)

    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()

        err_text = str(error.orig) if getattr(error, "orig", None) is not None else str(error)

        if "uq_user_linked_account" in err_text:
            linked_account = (
                await db.execute(
                    select(UserLinkedAccount)
                    .options(selectinload(UserLinkedAccount.user))
                    .where(
                        UserLinkedAccount.provider == sign_in_provider,
                        UserLinkedAccount.provider_user_id == provider_user_id,
                        ~UserLinkedAccount.is_deleted
                    )
                )
            ).scalar_one_or_none()

            if not linked_account or not linked_account.user or linked_account.user.is_deleted:
                raise UnauthorizedException("Linked account or user invalid.")

            return UserRead.model_validate(linked_account.user)

        if "uq_user_email_not_deleted" in err_text:
            existing_user = (
                await db.execute(
                    select(User)
                    .where(
                        User.email == email,
                        ~User.is_deleted
                    )
                )
            ).scalar_one_or_none()

            if not existing_user:
                raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

            new_linked_account = UserLinkedAccount(
                user_id=existing_user.id,
                provider=sign_in_provider,
                provider_user_id=provider_user_id
            )

            db.add(new_linked_account)

            try:
                await db.commit()
            except IntegrityError as inner_error:
                await db.rollback()

                err_text2 = (
                    str(inner_error.orig)
                    if getattr(inner_error, "orig", None) is not None
                    else str(inner_error)
                )

                if "uq_user_linked_account" in err_text2:
                    linked_account = (
                        await db.execute(
                            select(UserLinkedAccount)
                            .options(selectinload(UserLinkedAccount.user))
                            .where(
                                UserLinkedAccount.provider == sign_in_provider,
                                UserLinkedAccount.provider_user_id == provider_user_id,
                                ~UserLinkedAccount.is_deleted
                            )
                        )
                    ).scalar_one_or_none()

                    if not linked_account or not linked_account.user or linked_account.user.is_deleted:
                        raise UnauthorizedException("Linked account or user invalid.")

                    return UserRead.model_validate(linked_account.user)

                raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

            await db.refresh(existing_user)

            return UserRead.model_validate(existing_user)

        raise DuplicateValueException("Unable to complete signup due to a conflict. Please try again.")

    await db.refresh(user)

    return UserRead.model_validate(user)

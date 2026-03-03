import asyncio
import logging

from sqlalchemy import select

from ..app.core.config import settings
from ..app.core.db.database import AsyncSession, local_session
from ..app.core.security import get_password_hash
from ..app.models.admin_user import AdminUser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_first_superuser(session: AsyncSession) -> None:
    email = settings.ADMIN_EMAIL
    username = settings.ADMIN_USERNAME

    if await session.scalar(
        select(AdminUser).where(
            AdminUser.email == email,
            AdminUser.is_deleted.is_(False),
        )
    ):
        logger.info("Admin superuser '%s' already exists.", username)
        return

    try:
        session.add(
            AdminUser(
                username=username,
                email=email,
                hashed_password = get_password_hash(settings.ADMIN_PASSWORD.get_secret_value()),
                is_superuser=True,
            )
        )
        await session.commit()
        logger.info("Admin superuser '%s' created successfully.", username)

    except Exception:
        logger.exception("Failed to create admin superuser '%s'.", username)
        await session.rollback()
        raise


async def main() -> None:
    async with local_session() as session:
        await create_first_superuser(session)


if __name__ == "__main__":
    asyncio.run(main())

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
    try:
        email = settings.ADMIN_EMAIL
        username = settings.ADMIN_USERNAME
        hashed_password = get_password_hash(settings.ADMIN_PASSWORD)

        stmt = select(AdminUser).where(
            AdminUser.email == email,
            AdminUser.is_deleted.is_(False),
        )
        result = await session.execute(stmt)
        existing_user = result.scalar_one_or_none()

        if existing_user is None:
            new_admin = AdminUser(
                username=username,
                email=email,
                hashed_password=hashed_password,
                is_superuser=True,
                first_name=None,
                last_name=None,
                phone_number=None,
                profile_image_object_key=None,
                last_active_at=None,
            )
            session.add(new_admin)
            await session.commit()
            logger.info(f"Admin superuser {username} created successfully.")
        else:
            logger.info(f"Admin superuser {username} already exists.")

    except Exception as e:
        logger.error(f"Error creating admin superuser: {e}")
        await session.rollback()


async def main():
    async with local_session() as session:
        await create_first_superuser(session)


if __name__ == "__main__":
    asyncio.run(main())

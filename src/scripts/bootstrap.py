import asyncio

from app.core.db.database import local_session
from scripts.create_default_role import create_default_role
from scripts.create_first_superuser import create_first_superuser
from scripts.create_tier import create_tier
from scripts.seed_permissions import seed_permissions


async def main():
    async with local_session() as session:
        await seed_permissions(session)
        await create_default_role(session)
        await create_first_superuser(session)
        await create_tier(session)
        print("Bootstrap completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())

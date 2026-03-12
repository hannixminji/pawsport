import re
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass

from ..config import settings


class Base(DeclarativeBase, MappedAsDataclass):
    pass


DATABASE_PREFIX = settings.POSTGRES_ASYNC_PREFIX
DATABASE_URI = settings.POSTGRES_URI

if settings.POSTGRES_URL:
    DATABASE_URI = re.sub(r'[?&](sslmode|channel_binding)=[^&]*', '', DATABASE_URI)
    DATABASE_URI = DATABASE_URI.rstrip('?&')
    DATABASE_URI += ('&' if '?' in DATABASE_URI else '?') + 'ssl=require'

DATABASE_URL = f"{DATABASE_PREFIX}{DATABASE_URI}"

async_engine = create_async_engine(DATABASE_URL, echo=False, future=True)

local_session = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def async_get_db() -> AsyncGenerator[AsyncSession]:
    async with local_session() as db:
        yield db

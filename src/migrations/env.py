import asyncio
import importlib
import pkgutil
import re
from logging.config import fileConfig

import geoalchemy2  # noqa: F401
from alembic import context
from geoalchemy2 import alembic_helpers
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db.database import Base

POSTGIS_TABLES = {
    "spatial_ref_sys", "geography_columns", "geometry_columns",
    "raster_columns", "raster_overviews",
}
POSTGIS_SCHEMAS = {"topology", "tiger", "tiger_data"}


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table":
        if name in POSTGIS_TABLES:
            return False
        schema = getattr(object, "schema", None)
        if schema in POSTGIS_SCHEMAS:
            return False
        if reflected and compare_to is None:
            return False
    if type_ == "schema" and name in POSTGIS_SCHEMAS:
        return False
    return True


config = context.config

uri = settings.POSTGRES_URI
uri = re.sub(r'[?&](sslmode|channel_binding)=[^&]*', '', uri)
uri = uri.rstrip('?&')
uri += ('&' if '?' in uri else '?') + 'ssl=require'

config.set_main_option(
    "sqlalchemy.url",
    f"{settings.POSTGRES_ASYNC_PREFIX}{uri}",
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def import_models(package_name):
    package = importlib.import_module(package_name)
    for _, module_name, _ in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(module_name)


import_models("app.models")
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        process_revision_directives=alembic_helpers.writer,
        render_item=alembic_helpers.render_item,
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

# ruff: noqa: I001
import asyncio
from contextlib import suppress
from logging.config import fileConfig
from typing import Any

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy_file import FileField

from djgram.db import db_engine
from djgram.db.pydantic_field import ExtendedPydanticType
from tg_bot.main import BaseModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseModel.metadata

config.set_main_option(
    "sqlalchemy.url",
    db_engine.url.render_as_string(hide_password=False),
)


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")  # noqa: ERA001
# ... etc.


def render_item(type_: str, obj: Any, autogen_context: AutogenContext):
    """Apply custom rendering for selected items."""

    if type_ == "type" and isinstance(obj, FileField):
        autogen_context.imports.add("from sqlalchemy_file import FileField")
        return "FileField()"

    if type_ == "type" and isinstance(obj, ExtendedPydanticType):
        return obj.alembic_definition(autogen_context)

    if type_ == "type" and obj.__class__.__module__.startswith("sqlalchemy_utils."):
        autogen_context.imports.add(f"import {obj.__class__.__module__}")
        if hasattr(obj, "choices"):
            return f"{obj.__class__.__module__}.{obj.__class__.__name__}(choices={obj.choices})"

        return f"{obj.__class__.__module__}.{obj.__class__.__name__}()"

    # default rendering for other objects
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # https://gist.github.com/h4/fc9b6d350544ff66491308b535762fee?permalink_comment_id=4489224#gistcomment-4489224
        # set search path on the connection, which ensures that
        # PostgreSQL will emit all CREATE / ALTER / DROP statements
        # in terms of this schema by default
        if target_metadata.schema is not None:
            await connection.execute(text(f'set search_path to "{target_metadata.schema}"'))
            # in SQLAlchemy v2+ the search path change needs to be committed
            with suppress(AttributeError):
                await connection.commit()
            # make use of non-supported SQLAlchemy attribute to ensure
            # the dialect reflects tables in terms of the current tenant name
            connection.dialect.default_schema_name = target_metadata.schema

        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

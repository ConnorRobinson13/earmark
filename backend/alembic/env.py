from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base
from app import models  # noqa: F401 — register models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Which database to migrate — the caller's choice, not the environment's.

    Programmatic callers set `db_url` on the config's `attributes` — that is how
    the test harness hands over its throwaway database. Only when nobody has
    chosen do we fall back to `settings`, and reading it here rather than at
    import means a caller that supplies a URL never constructs the compose one
    at all. `alembic upgrade head` under compose supplies nothing, so it still
    migrates exactly the database it always did.
    """
    url = config.attributes.get("db_url")
    if url:
        return url

    from app.config import settings  # local — the fallback shouldn't cost an import

    return settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Injected into the section rather than set as a main option: `set_main_option`
    # runs the value through ConfigParser interpolation, which would choke on a
    # password containing '%'.
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

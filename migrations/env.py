import os

from alembic import context
from career import models  # noqa: F401
from career.db import Base, database_url
from sqlalchemy import create_engine, pool

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # pgvector storage is a PostgreSQL-specific migration, not a portable ORM table.
    if type_ == "table" and name == "evidence_embeddings":
        return False
    # 0003 owns this PostgreSQL expression index. It is intentionally absent
    # from portable ORM metadata; autogenerate must not propose deleting it.
    if (
        type_ == "index" and reflected and compare_to is None
        and name == "ix_evidence_fts" and obj.table.name == "evidences"
    ):
        return False
    return True


url = database_url(
    os.getenv("DATABASE_MIGRATION_URL") or os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
)
if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection_options = {"connect_timeout": 10} if url.get_backend_name() == "postgresql" else {}
    with create_engine(url, poolclass=pool.NullPool, connect_args=connection_options).connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object
        )
        with context.begin_transaction():
            context.run_migrations()

"""Schema changes are explicit deployment steps, not side effects of HTTP requests."""
from contextlib import nullcontext
from alembic import context
from src.persistence.database import engine
from src.persistence.models import Base


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name == "research"
    return True


if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=Base.metadata, literal_binds=True, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = context.config.attributes.get("connection")
    with nullcontext(supplied) if supplied is not None else engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, include_schemas=True,
                          include_name=include_name, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

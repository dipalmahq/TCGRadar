from logging.config import fileConfig
from alembic import context

from app.config import get_settings
from app.db import Base, make_engine
from app import models  # noqa: F401 -- register model metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
url = get_settings().database_url
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get('connection')
    from contextlib import nullcontext
    with (nullcontext(supplied) if supplied is not None else make_engine(url).connect()) as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

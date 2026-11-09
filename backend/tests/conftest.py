import os
from pathlib import Path
import uuid

os.environ.setdefault("RADAR_DATABASE_URL", "sqlite://")
os.environ.setdefault("RADAR_ENVIRONMENT", "development")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import Base, make_engine
from app.models import Merchant
from app.seed import seed


@pytest.fixture
def settings():
    return Settings(_env_file=None, environment="development", database_url="sqlite://", shops_file=Path("not-a-shop-config.json"), request_delay_seconds=0, stale_after_minutes=30, refresh_interval_seconds=300, refresh_batch_size=6, notifications_enabled=True, api_key="test-team-key", discord_webhook_url="https://discord.com/api/webhooks/123/test-token", telegram_bot_token="", telegram_chat_id="")


@pytest.fixture
def factory(tmp_path, settings):
    postgres_url = os.environ.get("RADAR_TEST_DATABASE_URL")
    admin = None
    schema = "radar_test_" + uuid.uuid4().hex
    if postgres_url:
        admin = make_engine(postgres_url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(postgres_url, connect_args={"options": f"-csearch_path={schema}"})
    else:
        engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        seed(db, settings)
        db.add(Merchant(slug="fixture-shop", name="Fixture Shop", base_url="https://fixture.example", country="DE", adapter="shopify", config={"max_pages": 1, "page_size": 50}))
        db.commit()
    yield factory
    engine.dispose()
    if admin:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()

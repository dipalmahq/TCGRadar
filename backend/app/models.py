from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


class Game(Base):
    __tablename__ = "games"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    product_line: Mapped[str] = mapped_column(String(100))


class Expansion(Base):
    __tablename__ = "expansions"
    __table_args__ = (UniqueConstraint("game_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    expansion_id: Mapped[int | None] = mapped_column(ForeignKey("expansions.id"), index=True)
    identity_key: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(20), default="unknown")
    product_type: Mapped[str] = mapped_column(String(40))
    booster_count: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str] = mapped_column(String(40), default="sealed")
    edition: Mapped[str] = mapped_column(String(200), default="unknown")
    gtin: Mapped[str | None] = mapped_column(String(20))
    match_confidence: Mapped[str] = mapped_column(String(30), default="isolated")
    game: Mapped[Game] = relationship()
    expansion: Mapped[Expansion | None] = relationship()


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2))
    adapter: Mapped[str] = mapped_column(String(40))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=600)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_offer_count: Mapped[int] = mapped_column(Integer, default=0)
    last_scanned_count: Mapped[int] = mapped_column(Integer, default=0)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("merchant_id", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    price_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    availability: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    last_known_availability: Mapped[str] = mapped_column(String(30), default="unknown")
    shipping_minor: Mapped[int | None] = mapped_column(Integer)
    shipping_country: Mapped[str | None] = mapped_column(String(2))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_error: Mapped[str | None] = mapped_column(String(500))
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    product: Mapped[Product] = relationship()
    merchant: Mapped[Merchant] = relationship()


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    price_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    availability: Mapped[str] = mapped_column(String(30))


class OfferEvent(Base):
    __tablename__ = "offer_events"
    __table_args__ = (UniqueConstraint("offer_id", "revision", "kind"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    previous: Mapped[dict | None] = mapped_column(JSON)
    current: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    offer: Mapped[Offer] = relationship()


class SearchRule(Base):
    __tablename__ = "search_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    query: Mapped[str] = mapped_column(String(200), default="")
    game_id: Mapped[int | None] = mapped_column(ForeignKey("games.id"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    merchant_id: Mapped[int | None] = mapped_column(ForeignKey("merchants.id"))
    set_code: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(20))
    product_type: Mapped[str | None] = mapped_column(String(40))
    game_ids: Mapped[list] = mapped_column(JSON, default=list)
    merchant_ids: Mapped[list] = mapped_column(JSON, default=list)
    set_codes: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    product_types: Mapped[list] = mapped_column(JSON, default=list)
    max_price_minor: Mapped[int | None] = mapped_column(Integer)
    include_preorders: Mapped[bool] = mapped_column(Boolean, default=False)
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["discord"])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatchTarget(Base):
    __tablename__ = "watch_targets"
    __table_args__ = (UniqueConstraint("merchant_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    url: Mapped[str] = mapped_column(String(1000))
    max_price_minor: Mapped[int | None] = mapped_column(Integer)
    channels: Mapped[list] = mapped_column(JSON, default=lambda: ["discord"])
    include_preorders: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("event_id", "channel"), Index("ix_notifications_due", "status", "next_attempt_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("offer_events.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    payload: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

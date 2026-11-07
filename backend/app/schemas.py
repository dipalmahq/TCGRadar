from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal["discord", "telegram"]
Language = Literal["de", "en", "ja", "zh", "fr", "it", "ko", "unknown"]
ProductType = Literal["booster", "display", "etb", "bundle", "case", "tin", "collection", "blister", "starter_deck"]


class RuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    query: str = Field(default="", max_length=200)
    game_id: int | None = Field(default=None, gt=0)
    product_id: int | None = Field(default=None, gt=0)
    merchant_id: int | None = Field(default=None, gt=0)
    set_code: str | None = Field(default=None, max_length=100)
    language: Language | None = None
    product_type: ProductType | None = None
    game_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=50)
    merchant_ids: list[Annotated[int, Field(gt=0)]] = Field(default_factory=list, max_length=50)
    set_codes: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=50)
    languages: list[Language] = Field(default_factory=list, max_length=50)
    product_types: list[ProductType] = Field(default_factory=list, max_length=50)
    max_price_minor: int | None = Field(default=None, ge=1, le=100_000_000)
    include_preorders: bool = False
    channels: list[Channel] = Field(default_factory=lambda: ["discord"], min_length=1, max_length=2)
    enabled: bool = True

    @model_validator(mode="after")
    def compatible_filters(self):
        for singular, plural in (("game_id", "game_ids"), ("merchant_id", "merchant_ids"), ("set_code", "set_codes"), ("language", "languages"), ("product_type", "product_types")):
            if getattr(self, singular) is not None and getattr(self, plural):
                raise ValueError(f"Use either {singular} or {plural}")
            setattr(self, plural, list(dict.fromkeys(getattr(self, plural))))
        return self

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value.strip()


class WatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=12, max_length=1000)
    max_price_minor: int | None = Field(default=None, ge=1, le=100_000_000)
    channels: list[Channel] = Field(default_factory=lambda: ["discord"], min_length=1, max_length=2)
    include_preorders: bool = False


class Toggle(BaseModel):
    enabled: bool


class TestNotification(BaseModel):
    channel: Channel

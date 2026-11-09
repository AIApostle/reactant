from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class ProductCreate(RequestModel):
    source: Literal["manual"] = "manual"
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    category: str | None = Field(default=None, max_length=120)
    price_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    stock_quantity: int | None = Field(default=None, ge=0)
    status: Literal["active", "draft", "archived"] = "active"
    agent_enabled: bool = True
    image_asset_ids: list[UUID] = Field(default_factory=list, max_length=6)


class ProductUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    category: str | None = Field(default=None, max_length=120)
    price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    stock_quantity: int | None = Field(default=None, ge=0)
    status: Literal["active", "draft", "archived"] | None = None
    agent_enabled: bool | None = None
    image_asset_ids: list[UUID] | None = Field(default=None, max_length=6)


class ProductResponse(RequestModel):
    id: UUID
    business_id: UUID
    source: str
    name: str
    description: str | None
    category: str | None
    price_minor: int
    currency: str
    stock_quantity: int | None
    status: str
    agent_enabled: bool
    image_asset_ids: list[UUID]
    image_urls: list[str] = Field(default_factory=list, max_length=6)
    created_at: datetime
    updated_at: datetime


class MediaUploadCreate(RequestModel):
    file_name: str = Field(min_length=1, max_length=255)
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024)
    purpose: Literal["catalog_product"] = "catalog_product"


class MediaUploadResponse(RequestModel):
    asset_id: UUID
    upload_url: str
    required_headers: dict[str, str]
    expires_at: datetime


class MediaAssetResponse(RequestModel):
    id: UUID
    business_id: UUID
    file_name: str
    content_type: str
    size_bytes: int
    status: Literal["pending", "validated", "rejected"]
    created_at: datetime

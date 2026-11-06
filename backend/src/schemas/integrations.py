from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, Field

from src.schemas.common import RequestModel


Provider = Literal[
    "woocommerce",
    "telegram",
    "paypal",
    "shopify",
    "whatsapp",
]


class IntegrationCredentials(RequestModel):
    store_url: AnyHttpUrl | None = None
    consumer_key: str | None = Field(default=None, min_length=1, max_length=4096)
    consumer_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    bot_token: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_id: str | None = Field(default=None, min_length=1, max_length=256)


class IntegrationCreate(RequestModel):
    provider: Provider
    credentials: IntegrationCredentials


class IntegrationResponse(RequestModel):
    id: UUID
    provider: str
    category: str
    status: str
    connected_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    granted_scopes: list[str]
    sync_status: str


class IntegrationAuthorizationResponse(RequestModel):
    authorization_url: AnyHttpUrl
    expires_at: datetime


class IntegrationSyncResponse(RequestModel):
    integration_id: UUID
    status: Literal["queued"]
    job_id: UUID

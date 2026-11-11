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
    "website_chat",
]


class IntegrationCredentials(RequestModel):
    store_url: AnyHttpUrl | None = None
    mcp_endpoint: AnyHttpUrl | None = None
    shop_domain: str | None = Field(default=None, min_length=1, max_length=255)
    consumer_key: str | None = Field(default=None, min_length=1, max_length=4096)
    consumer_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    access_token: str | None = Field(default=None, min_length=1, max_length=4096)
    bot_token: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_secret: str | None = Field(default=None, min_length=1, max_length=4096)
    webhook_id: str | None = Field(default=None, min_length=1, max_length=256)
    allowed_origin: str | None = Field(default=None, min_length=1, max_length=512)
class IntegrationCreate(RequestModel):
    provider: Provider
    credentials: IntegrationCredentials


class PayPalWebhookConfigurationRequest(RequestModel):
    webhook_id: str = Field(min_length=1, max_length=256)


class IntegrationResponse(RequestModel):
    id: UUID
    provider: str
    allowed_origin: str | None = None
    category: str
    status: str
    connected_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    granted_scopes: list[str]
    sync_status: str


class TelegramSetupResponse(RequestModel):
    webhook_url: AnyHttpUrl
    bot_username: str
    bot_name: str


class PayPalWebhookSetupResponse(RequestModel):
    webhook_url: AnyHttpUrl
    configured: bool


class IntegrationAuthorizationResponse(RequestModel):
    authorization_url: AnyHttpUrl
    expires_at: datetime


class IntegrationSyncResponse(RequestModel):
    integration_id: UUID
    status: Literal["queued"]
    job_id: UUID

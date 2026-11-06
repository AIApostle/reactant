from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic import Field


class ProviderWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str | None = None
    event_type: str | None = None
    data: dict[str, Any] | None = None


class WebhookAck(BaseModel):
    received: bool
    duplicate: bool = False

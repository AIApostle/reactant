from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class RealtimeTicketResponse(RequestModel):
    ticket: str
    websocket_url: str
    expires_at: datetime


class RealtimeSubscribe(RequestModel):
    type: Literal["subscribe"]
    topics: list[
        Literal[
            "conversations",
            "owner_assistant",
            "approvals",
            "orders",
            "integrations",
            "notifications",
        ]
    ] = Field(min_length=1, max_length=6)
    cursor: str | None = Field(default=None, max_length=512)


class RealtimeEvent(RequestModel):
    id: UUID
    type: str
    business_id: UUID
    occurred_at: datetime
    data: dict[str, object]

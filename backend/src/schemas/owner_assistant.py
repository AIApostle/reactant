from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class OwnerMessageCreate(RequestModel):
    text: str = Field(min_length=1, max_length=10000)
    client_message_id: UUID | None = None


class OwnerMessageResponse(RequestModel):
    id: UUID
    thread_id: UUID
    sender_type: Literal["user", "agent"]
    sender_id: str
    display_name: str
    kind: Literal[
        "text",
        "clarification",
        "approval_request",
        "exception",
        "status_update",
        "summary",
    ]
    text: str
    approval_id: UUID | None
    created_at: datetime
    read_at: datetime | None


class OwnerThreadResponse(RequestModel):
    id: UUID
    business_id: UUID
    created_at: datetime


class OwnerAssistantStatusResponse(RequestModel):
    provider: Literal["strands"]
    enabled: bool
    available: bool
    model_id: str | None
    reason: Literal[
        "ready",
        "disabled",
        "missing_google_key",
        "missing_openrouter_key",
        "missing_service_key",
    ]


class OwnerTelegramChannelStatusResponse(RequestModel):
    telegram_connected: bool
    paired: bool
    paired_at: datetime | None


class OwnerTelegramPairingResponse(RequestModel):
    pairing_code: str
    bot_username: str = Field(min_length=1, max_length=64)
    expires_at: datetime


class OwnerMessageAccepted(RequestModel):
    message: OwnerMessageResponse
    agent_run_id: UUID
    agent_run_status: Literal["queued", "running", "succeeded", "failed"]


class AgentRunStatusResponse(RequestModel):
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None


class InternalOwnerMessageCreate(RequestModel):
    agent_run_id: UUID
    idempotency_key: UUID
    sender_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="Business agent", max_length=160)
    kind: Literal[
        "text",
        "clarification",
        "approval_request",
        "exception",
        "status_update",
        "summary",
    ]
    text: str = Field(min_length=1, max_length=10000)
    approval_id: UUID | None = None

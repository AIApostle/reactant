from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class SetupChecklistItem(RequestModel):
    key: str
    label: str
    status: Literal["not_started", "in_progress", "complete", "attention_required"]
    action_url: str | None = None


class SetupChecklistResponse(RequestModel):
    items: list[SetupChecklistItem]


class DashboardSummaryResponse(RequestModel):
    metrics: dict[str, int | str | None] = Field(default_factory=dict)
    agent_status: str
    recent_conversations: list[dict[str, object]] = Field(default_factory=list)
    recent_orders: list[dict[str, object]] = Field(default_factory=list)
    pending_approvals: list[dict[str, object]] = Field(default_factory=list)


class AuditEventResponse(RequestModel):
    id: UUID
    actor_id: UUID | None
    event_type: str
    resource_type: str
    resource_id: str | None
    data: dict[str, object]
    created_at: datetime


class NotificationResponse(RequestModel):
    id: UUID
    type: str
    title: str
    body: str
    data: dict[str, object]
    read_at: datetime | None
    created_at: datetime

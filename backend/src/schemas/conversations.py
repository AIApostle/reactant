from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class ConversationUpdate(RequestModel):
    status: Literal["open", "needs_reply", "resolved"] | None = None
    assignee_id: UUID | None = None


class CustomerReplyCreate(RequestModel):
    text: str = Field(min_length=1, max_length=10000)
    visibility: Literal["customer"]


class HandoffUpdate(RequestModel):
    action: Literal["accept", "return"]


class ConversationLastMessage(RequestModel):
    text: str
    created_at: datetime


class ConversationResponse(RequestModel):
    id: UUID
    business_id: UUID
    channel: str
    status: str
    assignee_id: UUID | None
    handoff_status: str
    created_at: datetime
    updated_at: datetime
    customer_name: str = "Customer"
    last_message: ConversationLastMessage | None = None
    unread: bool = False


class CustomerMessageResponse(RequestModel):
    id: UUID
    conversation_id: UUID
    sender_type: str
    sender_id: str | None
    text: str
    visibility: Literal["customer", "staff"]
    delivery_status: Literal["queued", "sent", "failed"]
    created_at: datetime

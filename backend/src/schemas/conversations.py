from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from src.schemas.common import RequestModel


class ConversationUpdate(RequestModel):
    status: Literal["open", "needs_reply", "resolved"] | None = None
    assignee_id: UUID | None = None


class CustomerReplyAttachmentRequest(RequestModel):
    source: Literal["catalog", "conversation"]
    product_id: UUID | None = None
    message_id: UUID | None = None
    image_index: int = Field(default=0, ge=0, le=5)

    @model_validator(mode="after")
    def validate_source_reference(self):
        if self.source == "catalog":
            if self.product_id is None or self.message_id is not None:
                raise ValueError("Catalog images require a product reference only.")
        elif self.message_id is None or self.product_id is not None:
            raise ValueError("Conversation images require a message reference only.")
        return self


class CustomerReplyCreate(RequestModel):
    text: str = Field(default="", max_length=10000)
    visibility: Literal["customer"]
    attachments: list[CustomerReplyAttachmentRequest] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def require_message_content(self):
        if not self.text.strip() and not self.attachments:
            raise ValueError("A reply must include text or at least one image.")
        return self


class HandoffUpdate(RequestModel):
    action: Literal["accept", "return"]


class ConversationLastMessage(RequestModel):
    text: str
    created_at: datetime


class CustomerMessageAttachment(RequestModel):
    type: Literal["image"]
    url: str = Field(min_length=1, max_length=4096)
    alt: str = Field(default="Product image", max_length=500)
    source_index: int | None = None


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
    attachments: list[CustomerMessageAttachment] = Field(default_factory=list)

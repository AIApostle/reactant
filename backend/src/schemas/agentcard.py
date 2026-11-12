from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel

AgentCardState = Literal[
    "awaiting_customer",
    "awaiting_payment",
    "payment_processing",
    "payment_pending",
    "payment_failed",
    "paid",
    "cancelled",
    "expired",
    "reconciliation",
    "receipt_generation",
    "receipt_issued",
    "receipt_delivered",
    "partially_refunded",
    "refunded",
]


class AgentCardItemRequest(RequestModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=10000)


class AgentCardManualCheckoutRequest(RequestModel):
    items: list[AgentCardItemRequest] = Field(min_length=1, max_length=100)
    customer_name: str = Field(default="Sandbox checkout test", min_length=1, max_length=160)


class AgentCardCheckoutItem(RequestModel):
    product_id: UUID
    name: str
    description: str
    quantity: int
    unit_price_minor: int
    total_minor: int
    image_urls: list[str] = Field(default_factory=list)


class AgentCardCheckoutResponse(RequestModel):
    checkout_id: str
    public_transaction_id: str
    business_name: str
    items: list[AgentCardCheckoutItem]
    subtotal_minor: int
    discount_total_minor: int
    tax_total_minor: int
    delivery_total_minor: int
    total_amount_minor: int
    currency: str
    status: AgentCardState
    expires_at: datetime
    authorization_required: bool


class AgentCardConsentRequest(RequestModel):
    accepted: Literal[True]


class AgentCardPaymentRequest(RequestModel):
    accepted: Literal[True]
    payment_method: Literal["paypal", "card"] = "paypal"


class AgentCardRefundRequest(RequestModel):
    amount_minor: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=500)


class AgentCardCaptureRequest(RequestModel):
    provider_order_id: str = Field(min_length=1, max_length=128)


class AgentCardCheckoutStatus(RequestModel):
    public_transaction_id: str
    status: AgentCardState
    amount_minor: int
    currency: str
    updated_at: datetime
    receipt_url: str | None = None


class AgentCardPaymentResponse(RequestModel):
    status: Literal["payment_processing", "payment_pending", "paid", "payment_failed", "reconciliation"]
    approval_url: str | None = None

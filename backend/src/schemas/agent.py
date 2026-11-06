from typing import Literal
from uuid import UUID

from pydantic import Field

from src.schemas.common import RequestModel


class AgentPermissions(RequestModel):
    answer_product_questions: bool = True
    share_product_images: bool = False
    create_carts_and_orders: bool = False
    create_paypal_checkout: bool = False


class ApprovalPolicy(RequestModel):
    require_approval_for_checkout: bool = True
    checkout_threshold_minor: int | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    approver_member_ids: list[UUID] = Field(default_factory=list)


class AgentPermissionsUpdate(RequestModel):
    answer_product_questions: bool | None = None
    share_product_images: bool | None = None
    create_carts_and_orders: bool | None = None
    create_paypal_checkout: bool | None = None


class ApprovalPolicyUpdate(RequestModel):
    require_approval_for_checkout: bool | None = None
    checkout_threshold_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    approver_member_ids: list[UUID] | None = None


class AgentConfigUpdate(RequestModel):
    enabled: bool | None = None
    business_context: str | None = Field(default=None, max_length=20000)
    tone: str | None = Field(default=None, max_length=80)
    handoff_rule: str | None = Field(default=None, max_length=120)
    permissions: AgentPermissionsUpdate | None = None
    approval_policy: ApprovalPolicyUpdate | None = None


class AgentConfigResponse(RequestModel):
    enabled: bool
    status: str
    business_context: str
    tone: str
    handoff_rule: str
    permissions: AgentPermissions
    approval_policy: ApprovalPolicy


class AgentTestResponse(RequestModel):
    status: Literal["passed", "failed"]
    checks: list[dict[str, str | bool]]

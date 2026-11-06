import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from supabase import Client

from src.agent.config import get_agent_runtime_settings
from src.agent.runtime import build_business_agent, invoke_business_agent
from src.agent.worker import require_agent_runtime
from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.agent import (
    AgentConfigResponse,
    AgentConfigUpdate,
    ApprovalPolicy,
    AgentPermissions,
    AgentTestResponse,
)
from src.schemas.common import ResourceEnvelope
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    execute,
    get_business_membership,
    require_matching_etag,
    require_role,
)


router = APIRouter()
logger = logging.getLogger(__name__)
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
DEFAULT_PERMISSIONS = AgentPermissions().model_dump()
DEFAULT_APPROVAL_POLICY = ApprovalPolicy().model_dump(mode="json")
CONFIG_FIELDS = (
    "enabled,status,business_context,tone,handoff_rule,permissions,approval_policy,version"
)


def _config_response(row: dict[str, Any]) -> AgentConfigResponse:
    return AgentConfigResponse(
        enabled=row["enabled"],
        status=row["status"],
        business_context=row["business_context"],
        tone=row["tone"],
        handoff_rule=row["handoff_rule"],
        permissions=AgentPermissions(**{**DEFAULT_PERMISSIONS, **row.get("permissions", {})}),
        approval_policy=ApprovalPolicy(
            **{**DEFAULT_APPROVAL_POLICY, **row.get("approval_policy", {})}
        ),
    )


@router.get(
    "/businesses/{business_id}/agent",
    response_model=ResourceEnvelope[AgentConfigResponse],
)
def get_agent_config(
    business_id: UUID,
    request: Request,
    response: Response,
    user: User,
    client: Database,
) -> ResourceEnvelope[AgentConfigResponse]:
    get_business_membership(client, business_id, user.id)
    row = execute(
        client.table("agent_configs")
        .select(CONFIG_FIELDS)
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    response.headers["ETag"] = f'"{row["version"]}"'
    return ResourceEnvelope(
        data=_config_response(row),
        request_id=request.state.request_id,
    )


@router.patch(
    "/businesses/{business_id}/agent",
    response_model=ResourceEnvelope[AgentConfigResponse],
)
def update_agent_config(
    business_id: UUID,
    body: AgentConfigUpdate,
    request: Request,
    response: Response,
    user: User,
    client: Database,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ResourceEnvelope[AgentConfigResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    current = execute(
        client.table("agent_configs")
        .select(CONFIG_FIELDS)
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    if not current:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    require_matching_etag(if_match, current["version"])
    changes = body.model_dump(exclude_unset=True, exclude={"permissions", "approval_policy"})
    if body.permissions is not None:
        changes["permissions"] = {
            **DEFAULT_PERMISSIONS,
            **current.get("permissions", {}),
            **body.permissions.model_dump(exclude_unset=True),
        }
    if body.approval_policy is not None:
        approval_policy = {
            **DEFAULT_APPROVAL_POLICY,
            **current.get("approval_policy", {}),
            **body.approval_policy.model_dump(exclude_unset=True),
        }
        approver_ids = approval_policy["approver_member_ids"]
        if approver_ids:
            members = execute(
                client.table("business_members")
                .select("id,role")
                .eq("business_id", str(business_id))
                .in_("id", [str(member_id) for member_id in approver_ids])
            )
            if (
                len(members) != len(set(approver_ids))
                or any(member["role"] == "read_only" for member in members)
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"code": "validation_error", "message": "The approval policy contains an invalid approver."},
                )
        changes["approval_policy"] = approval_policy
    changes["version"] = current["version"] + 1
    updated = execute(
        client.table("agent_configs")
        .update(changes)
        .eq("business_id", str(business_id))
        .eq("version", current["version"])
        .select(CONFIG_FIELDS)
        .maybe_single()
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"code": "stale_resource", "message": "The resource has changed. Refresh and retry."},
        )
    response.headers["ETag"] = f'"{updated["version"]}"'
    return ResourceEnvelope(
        data=_config_response(updated),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/agent/test",
    response_model=ResourceEnvelope[AgentTestResponse],
)
def test_agent_config(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[AgentTestResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    require_agent_runtime()
    business = execute(
        client.table("businesses")
        .select("name,country,currency,return_policy,delivery_policy")
        .eq("id", str(business_id))
        .single()
    )
    config = execute(
        client.table("agent_configs")
        .select("business_context,tone,handoff_rule")
        .eq("business_id", str(business_id))
        .maybe_single()
    )
    try:
        agent = build_business_agent(
            client=client,
            business_id=str(business_id),
            settings=get_agent_runtime_settings(),
            business=business,
            agent_config=config,
            history=[],
        )
        invoke_business_agent(agent, "Reply with a brief runtime check confirmation.")
    except Exception as error:
        logger.error(
            "Agent configuration test failed business_id=%s exception_type=%s",
            business_id,
            type(error).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "agent_runtime_unavailable",
                "message": "The agent runtime test could not be completed.",
            },
        ) from error
    return ResourceEnvelope(
        data=AgentTestResponse(
            status="passed",
            checks=[{"name": "agent_runtime", "passed": True}],
        ),
        request_id=request.state.request_id,
    )

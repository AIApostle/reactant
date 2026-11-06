from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from supabase import Client

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.common import CollectionEnvelope, PaginationMeta
from src.schemas.search import SearchResult
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import execute, get_business_membership


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
SearchType = Literal["conversation", "order", "product"]


@router.get(
    "/businesses/{business_id}/search",
    response_model=CollectionEnvelope[SearchResult],
)
def search_business(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    q: str = Query(min_length=1, max_length=160),
    types: list[SearchType] | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
) -> CollectionEnvelope[SearchResult]:
    get_business_membership(client, business_id, user.id)
    selected_types = set(types or ["conversation", "order", "product"])
    results: list[SearchResult] = []
    if "product" in selected_types:
        rows = execute(
            client.table("products")
            .select("id,name,category,status")
            .eq("business_id", str(business_id))
            .neq("status", "archived")
            .ilike("name", f"%{q}%")
            .limit(limit)
        )
        results.extend(
            SearchResult(
                type="product",
                id=row["id"],
                title=row["name"],
                subtitle=row["category"],
                resource_url=f"/businesses/{business_id}/products/{row['id']}",
            )
            for row in rows
        )
    if "order" in selected_types:
        rows = execute(
            client.table("orders")
            .select("id,customer_name,status,payment_status")
            .eq("business_id", str(business_id))
            .ilike("customer_name", f"%{q}%")
            .limit(limit)
        )
        results.extend(
            SearchResult(
                type="order",
                id=row["id"],
                title=row["customer_name"],
                subtitle=f"{row['status']} · {row['payment_status']}",
                resource_url=f"/businesses/{business_id}/orders/{row['id']}",
            )
            for row in rows
        )
    if "conversation" in selected_types:
        rows = execute(
            client.table("conversations")
            .select("id,channel,status,provider_conversation_id")
            .eq("business_id", str(business_id))
            .ilike("provider_conversation_id", f"%{q}%")
            .limit(limit)
        )
        results.extend(
            SearchResult(
                type="conversation",
                id=row["id"],
                title=row.get("provider_conversation_id") or f"{row['channel']} conversation",
                subtitle=row["status"],
                resource_url=f"/businesses/{business_id}/conversations/{row['id']}",
            )
            for row in rows
        )
    results = results[:limit]
    return CollectionEnvelope(
        data=results,
        meta=PaginationMeta(next_cursor=None, has_more=False),
        request_id=request.state.request_id,
    )

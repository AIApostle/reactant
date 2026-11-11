import re
from typing import Any

import httpx
from storage3.utils import StorageException

from strands import Agent, tool
from strands.models.openai import OpenAIModel
from strands.types.agent import Limits
from supabase import Client

from src.agent.config import AgentRuntimeSettings
from src.agent.customer_images import CustomerImage
from src.agent.memory import (
    get_memory_config,
    memory_namespace,
    recall_memories,
    remember_fact,
)
from src.agentcard.service import create_agentcard_transaction as create_agentcard_transaction_service
from src.agent.prompts import build_business_system_prompt
from src.schemas.agentcard import AgentCardItemRequest
from src.supabase.client import get_supabase_settings
from src.supabase.repository import execute


MAX_AGENT_TURNS = 6
MAX_AGENT_OUTPUT_TOKENS = 1200
MAX_AGENT_TOTAL_TOKENS = 8000
MAX_PRODUCT_SEARCH_RESULTS = 8
MAX_WEB_SEARCH_RESULTS = 5
MAX_PRODUCT_IMAGE_RESULTS = 3


def sanitize_customer_response(text: str) -> str:
    """Keep customer replies readable and prevent private media URLs leaking into text."""
    cleaned = re.sub(r"\[([^\]]+)\]\(\s*https?://[^)\s]+\s*\)", r"\1", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"(\*\*|__|`)", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(?:[-*]\s*)?(?:image|photo|picture)\s*:\s*.*$", "", cleaned)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _product_image_urls(
    client: Client,
    business_id: str,
    row: dict[str, Any],
) -> list[str]:
    provider_data = row.get("provider_data") or {}
    image_urls = provider_data.get("image_urls", []) if isinstance(provider_data, dict) else []
    urls = [url for url in image_urls if isinstance(url, str) and url.startswith("https://")]
    asset_ids = row.get("image_asset_ids") or []
    if asset_ids:
        assets = execute(
            client.table("media_assets")
            .select("delivery_path")
            .eq("business_id", business_id)
            .eq("status", "validated")
            .in_("id", asset_ids[:6])
        )
        for asset in assets:
            path = asset.get("delivery_path")
            if not isinstance(path, str):
                continue
            try:
                signed = client.storage.from_("product-media").create_signed_url(path, 3600)
                url = signed.get("signedURL") or signed.get("signed_url")
                if isinstance(url, str):
                    urls.append(url)
            except (StorageException, OSError, TypeError, ValueError):
                continue
    return list(dict.fromkeys(urls))[:MAX_PRODUCT_IMAGE_RESULTS]


def find_business_products(
    client: Client,
    business_id: str,
    query: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    normalized_query = query.strip()[:100]
    if not normalized_query:
        return []

    escaped_query = (
        normalized_query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    bounded_limit = max(1, min(limit, MAX_PRODUCT_SEARCH_RESULTS))
    rows = execute(
        client.table("products")
        .select("id,name,description,price_minor,currency,stock_quantity,provider_data,image_asset_ids")
        .eq("business_id", business_id)
        .eq("status", "active")
        .eq("agent_enabled", True)
        .ilike("name", f"%{escaped_query}%")
        .limit(bounded_limit)
    )
    return [
        {
            "product_id": row["id"],
            "name": row["name"],
            "description": (row.get("description") or "")[:500],
            "price_minor": row["price_minor"],
            "currency": row["currency"],
            "stock_quantity": row["stock_quantity"],
            "image_urls": _product_image_urls(client, business_id, row),
        }
        for row in rows
    ]


def search_web(query: str, limit: int = MAX_WEB_SEARCH_RESULTS) -> list[dict[str, str]]:
    normalized_query = query.strip()[:200]
    if not normalized_query:
        return []
    try:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={
                "q": normalized_query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    results: list[dict[str, str]] = []
    abstract = payload.get("AbstractText")
    abstract_url = payload.get("AbstractURL")
    if isinstance(abstract, str) and abstract and isinstance(abstract_url, str):
        results.append({"title": payload.get("Heading", "Web result"), "snippet": abstract[:500], "url": abstract_url})
    for topic in payload.get("RelatedTopics", []):
        if not isinstance(topic, dict):
            continue
        text = topic.get("Text")
        url = topic.get("FirstURL")
        if isinstance(text, str) and isinstance(url, str):
            results.append({"title": text.split(" - ", 1)[0][:160], "snippet": text[:500], "url": url})
        if len(results) >= max(1, min(limit, MAX_WEB_SEARCH_RESULTS)):
            break
    return results


def build_business_agent(
    client: Client,
    business_id: str,
    settings: AgentRuntimeSettings,
    business: dict[str, Any],
    agent_config: dict[str, Any] | None,
    history: list[dict[str, Any]],
    audience: str = "owner",
    memory_customer_reference: str | None = None,
    memory_opt_in: bool = False,
    conversation_id: str | None = None,
    customer_name: str = "Customer",
    customer_reference: str = "",
    idempotency_key: str | None = None,
    created_checkout_urls: list[str] | None = None,
    vision_enabled: bool = False,
) -> Agent:
    @tool
    def search_business_products(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Find active products in this business's catalog by product name."""
        products = find_business_products(client, business_id, query, limit)
        if audience == "customer":
            return [
                {
                    **product,
                    "image_urls": [],
                    "image_available": bool(product.get("image_urls")),
                }
                for product in products
            ]
        return products

    @tool
    def search_public_web(query: str) -> list[dict[str, str]]:
        """Search public web information when the business catalog does not answer the question."""
        return search_web(query)

    tools = [search_business_products, search_public_web]
    memory_config = (
        get_memory_config(business_id)
        if audience == "owner" or (memory_opt_in and memory_customer_reference)
        else None
    )
    if memory_config is not None:
        namespace = memory_namespace(
            business_id,
            audience=audience,
            customer_reference=memory_customer_reference,
        )

        @tool
        def search_business_memory(query: str) -> list[str]:
            """Recall relevant saved context from this authorized memory space."""
            return recall_memories(memory_config, namespace=namespace, query=query)

        @tool
        def remember_business_fact(content: str) -> dict[str, str]:
            """Save a durable, non-sensitive fact only when the user explicitly asks you to remember it."""
            remember_fact(memory_config, namespace=namespace, content=content)
            return {"status": "saved"}

        tools.extend([search_business_memory, remember_business_fact])
    if (
        audience == "customer"
        and get_supabase_settings().agentcard_enabled
        and bool((agent_config or {}).get("permissions", {}).get("create_carts_and_orders"))
        and bool((agent_config or {}).get("permissions", {}).get("create_paypal_checkout"))
        and conversation_id is not None
        and idempotency_key is not None
        and created_checkout_urls is not None
    ):
        @tool
        def create_agentcard_transaction(
            items: list[dict[str, Any]],
        ) -> dict[str, Any]:
            """Prepare a secure checkout from catalog product IDs and quantities after the customer explicitly agrees to buy. The server validates current prices and stock and calculates the total."""
            validated_items = [
                AgentCardItemRequest.model_validate(item)
                for item in items
            ]
            result = create_agentcard_transaction_service(
                client=client,
                business_id=business_id,
                conversation_id=conversation_id,
                customer_name=customer_name,
                customer_reference=customer_reference,
                items=validated_items,
                idempotency_key=idempotency_key,
            )
            checkout_url = result["checkout_url"]
            created_checkout_urls.append(checkout_url)
            return {
                "transaction_id": result["public_transaction_id"],
                "checkout_url": checkout_url,
                "amount_minor": result["snapshot"]["total_amount_minor"],
                "currency": result["snapshot"]["currency"],
                "expires_at": result["expires_at"],
                "status": result["status"],
            }

        tools.append(create_agentcard_transaction)

    if settings.openrouter_api_key is None:
        raise RuntimeError("The OpenRouter API key is not configured.")
    model = OpenAIModel(
        client_args={
            "api_key": settings.openrouter_api_key.get_secret_value(),
            "base_url": "https://openrouter.ai/api/v1",
        },
        model_id=(
            settings.openrouter_vision_model_id
            if vision_enabled
            else settings.openrouter_model_id
        ),
        params={"max_tokens": MAX_AGENT_OUTPUT_TOKENS},
    )

    system_prompt = build_business_system_prompt(
        business=business,
        agent_config=agent_config,
        audience=audience,
    )
    return Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        messages=history,
    )


def invoke_business_agent(
    agent: Agent,
    message: str,
    *,
    audience: str = "owner",
    images: list[CustomerImage] | None = None,
) -> str:
    prompt: str | list[dict[str, Any]] = message
    if images:
        prompt = [{"text": message}]
        prompt.extend(image.agent_content_block() for image in images)
    result = agent(
        prompt,
        limits=Limits(
            turns=MAX_AGENT_TURNS,
            output_tokens=MAX_AGENT_OUTPUT_TOKENS,
            total_tokens=MAX_AGENT_TOTAL_TOKENS,
        ),
    )
    response = str(result).strip()
    if not response:
        raise RuntimeError("The agent returned no text response.")
    response = sanitize_customer_response(response) if audience == "customer" else response
    return response[:10000]

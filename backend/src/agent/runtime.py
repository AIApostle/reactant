import hashlib
import logging
import re
import threading
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

import httpx
from fastapi import HTTPException
from google.genai.errors import APIError as GoogleAPIError
from openai import APIError as OpenAIAPIError
from pydantic import BaseModel, ConfigDict, Field
from storage3.utils import StorageException

from strands import Agent, tool
from strands.models.gemini import GeminiModel
from strands.models.model import Model
from strands.models.openai import OpenAIModel
from strands.types.agent import Limits
from strands.types.content import Messages, SystemContentBlock
from strands.types.exceptions import MaxTokensReachedException, ModelThrottledException
from strands.types.streaming import StreamEvent
from strands.types.tools import ToolChoice, ToolSpec
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
CUSTOMER_ORDER_ITEMS_INPUT_SCHEMA = {
    "json": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Exact product name returned by the catalog tool.",
                        },
                        "quantity": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10000,
                            "description": "Whole number of units requested.",
                        },
                    },
                    "required": ["product_name", "quantity"],
                    "additionalProperties": False,
                },
                "minItems": 1,
                "maxItems": 100,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
}
logger = logging.getLogger(__name__)
PROVIDER_FAILURES = (ModelThrottledException, GoogleAPIError, OpenAIAPIError)
PRODUCT_IMAGE_REQUEST = re.compile(
    r"\b(image|images|photo|photos|picture|pictures|show me|send me|see it)\b",
    re.I,
)
PRODUCT_IMAGE_QUERY_STOP_WORDS = {
    "a", "an", "and", "can", "could", "do", "for", "get", "guys", "have",
    "i", "image", "images", "it", "me", "message", "my", "of", "please",
    "picture", "pictures", "photo", "photos", "see", "show", "some", "the",
    "this", "that", "to", "want", "you", "one", "product", "products", "item",
    "items", "available",
}
INTERNAL_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b",
    re.I,
)
LABELED_INTERNAL_ID_PATTERN = re.compile(
    r"\b(?:internal[\s_-]+)?(?:product|catalog|inventory)[\s_-]*"
    r"(?:id|identifier|reference)\s*[:#]?\s*[a-z0-9_-]{4,}\b",
    re.I,
)


class CustomerOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product_name: str = Field(
        min_length=1,
        max_length=200,
        description="Exact product name returned by the catalog tool.",
    )
    quantity: int = Field(
        ge=1,
        le=10000,
        description="Whole number of units requested.",
    )


class FailoverModel(Model):
    def __init__(
        self,
        primary: Model,
        fallback: Model,
        *,
        primary_provider: str,
        fallback_provider: str,
        business_id: str,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.business_id = business_id
        self._fallback_active = False

    def update_config(self, **model_config: Any) -> None:
        self.primary.update_config(**model_config)
        self.fallback.update_config(**model_config)

    def get_config(self) -> Any:
        return self.primary.get_config()

    async def stream(
        self,
        messages: Messages,
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: ToolChoice | None = None,
        system_prompt_content: list[SystemContentBlock] | None = None,
        invocation_state: dict[str, Any] | None = None,
        cancel_signal: threading.Event | None = None,
        agent_metadata: Any = None,
        structured_output_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamEvent, None]:
        if self._fallback_active:
            events = [
                event
                async for event in self.fallback.stream(
                    messages,
                    tool_specs,
                    system_prompt,
                    tool_choice=tool_choice,
                    system_prompt_content=system_prompt_content,
                    invocation_state=invocation_state,
                    cancel_signal=cancel_signal,
                    agent_metadata=agent_metadata,
                    structured_output_model=structured_output_model,
                    **kwargs,
                )
            ]
        else:
            try:
                events = [
                    event
                    async for event in self.primary.stream(
                        messages,
                        tool_specs,
                        system_prompt,
                        tool_choice=tool_choice,
                        system_prompt_content=system_prompt_content,
                        invocation_state=invocation_state,
                        cancel_signal=cancel_signal,
                        agent_metadata=agent_metadata,
                        structured_output_model=structured_output_model,
                        **kwargs,
                    )
                ]
            except PROVIDER_FAILURES as error:
                self._fallback_active = True
                logger.warning(
                    "Agent model provider failed; switching to fallback for this run "
                    "business_id=%s primary=%s fallback=%s exception_type=%s",
                    self.business_id,
                    self.primary_provider,
                    self.fallback_provider,
                    type(error).__name__,
                )
                events = [
                    event
                    async for event in self.fallback.stream(
                        messages,
                        tool_specs,
                        system_prompt,
                        tool_choice=tool_choice,
                        system_prompt_content=system_prompt_content,
                        invocation_state=invocation_state,
                        cancel_signal=cancel_signal,
                        agent_metadata=agent_metadata,
                        structured_output_model=structured_output_model,
                        **kwargs,
                    )
                ]
        for event in events:
            yield event

    async def structured_output(
        self,
        output_model: type[BaseModel],
        prompt: Messages,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if self._fallback_active:
            results = [
                result
                async for result in self.fallback.structured_output(
                    output_model, prompt, system_prompt, **kwargs
                )
            ]
        else:
            try:
                results = [
                    result
                    async for result in self.primary.structured_output(
                        output_model, prompt, system_prompt, **kwargs
                    )
                ]
            except PROVIDER_FAILURES as error:
                self._fallback_active = True
                logger.warning(
                    "Agent model provider failed during structured output; switching "
                    "to fallback for this run business_id=%s primary=%s fallback=%s "
                    "exception_type=%s",
                    self.business_id,
                    self.primary_provider,
                    self.fallback_provider,
                    type(error).__name__,
                )
                results = [
                    result
                    async for result in self.fallback.structured_output(
                        output_model, prompt, system_prompt, **kwargs
                    )
                ]
        for result in results:
            yield result


def sanitize_customer_response(text: str) -> str:
    """Keep customer replies readable and hide internal media URLs and identifiers."""
    cleaned = re.sub(r"\[([^\]]+)\]\(\s*https?://[^)\s]+\s*\)", r"\1", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = LABELED_INTERNAL_ID_PATTERN.sub("", cleaned)
    cleaned = INTERNAL_UUID_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"(\*\*|__|`)", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(?:[-*]\s*)?(?:image|photo|picture)\s*:\s*.*$", "", cleaned)
    cleaned = re.sub(r"^\s*#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def customer_catalog_product(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": product["name"],
        "description": product.get("description", ""),
        "unit_price": format_minor_amount(
            product["price_minor"], product["currency"]
        ),
        "currency": product["currency"],
        "stock_quantity": product["stock_quantity"],
        "image_available": bool(product.get("image_urls")),
    }


def format_minor_amount(amount_minor: int, currency: str) -> str:
    amount = abs(amount_minor)
    sign = "-" if amount_minor < 0 else ""
    return (
        f"{currency.upper()} {sign}{amount // 100:,}."
        f"{amount % 100:02d}"
    )


def resolve_customer_checkout_items(
    items: list[CustomerOrderItem | dict[str, Any]],
    catalog_product_ids: dict[str, set[str]],
) -> list[AgentCardItemRequest]:
    resolved: list[AgentCardItemRequest] = []
    for raw_item in items:
        item = CustomerOrderItem.model_validate(raw_item)
        matching_ids = catalog_product_ids.get(item.product_name.strip().casefold(), set())
        if len(matching_ids) != 1:
            raise ValueError("Search for a specific catalog product before preparing checkout.")
        resolved.append(
            AgentCardItemRequest.model_validate(
                {
                    "product_id": next(iter(matching_ids)),
                    "quantity": item.quantity,
                }
            )
        )
    return resolved


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


def product_image_query(text: str, history: list[dict[str, Any]]) -> str:
    def clean(value: str) -> str:
        words = re.findall(r"[\w'-]+", value.lower())
        return " ".join(
            word for word in words if word not in PRODUCT_IMAGE_QUERY_STOP_WORDS
        )[:100]

    query = clean(PRODUCT_IMAGE_REQUEST.sub(" ", text))
    if query:
        return query
    for row in history:
        if row.get("sender_type") == "customer":
            query = clean(str(row.get("text", "")))
            if query:
                return query
    return ""


def product_image_attachments(
    products: list[dict[str, Any]],
    *,
    explicitly_requested: bool,
) -> list[dict[str, str]]:
    if not explicitly_requested:
        return []

    attachments: list[dict[str, str]] = []
    for product in products:
        name = product.get("name")
        if not isinstance(name, str):
            continue
        image_urls = product.get("image_urls")
        if not isinstance(image_urls, list):
            continue
        for url in image_urls:
            if isinstance(url, str) and url.startswith("https://"):
                attachments.append({"type": "image", "url": url, "alt": name})
                if len(attachments) >= MAX_PRODUCT_IMAGE_RESULTS:
                    return attachments
    return attachments


def product_image_reply(
    response: str,
    attachments: list[dict[str, str]],
    *,
    explicitly_requested: bool,
    delivery_failed: bool = False,
) -> str:
    if explicitly_requested:
        if not attachments:
            if delivery_failed:
                return "I couldn't send the product photo just now. Please try again later."
            return "I couldn't find a shareable photo for that product. Which item did you mean?"
        names = list(dict.fromkeys(item["alt"] for item in attachments))
        if len(names) == 1:
            return f"Here is a photo of {names[0]}."
        return f"Here are photos of {', '.join(names)}."
    if attachments:
        names = list(dict.fromkeys(item["alt"] for item in attachments))
        return f"{response.rstrip()}\n\nI've also included a photo of {', '.join(names)}."
    if delivery_failed:
        return f"{response.rstrip()}\n\nI couldn't send the product photo just now."
    return response


def include_secure_checkout_link(
    response: str,
    checkout_urls: list[str],
) -> str:
    if not checkout_urls:
        return response
    checkout_url = checkout_urls[-1]
    if checkout_url in response:
        return response
    return f"{response.rstrip()}\n\nSecure checkout: {checkout_url}"


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
    fields = "id,name,description,price_minor,currency,stock_quantity,provider_data,image_asset_ids"
    rows_by_id: dict[str, dict[str, Any]] = {}
    search_terms = [escaped_query]
    seen_terms = {escaped_query.lower()}
    for term in re.findall(r"[\w'-]+", normalized_query):
        escaped_term = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        if len(term) > 1 and escaped_term.lower() not in seen_terms:
            search_terms.append(escaped_term)
            seen_terms.add(escaped_term.lower())
    for term in search_terms:
        rows = execute(
            client.table("products")
            .select(fields)
            .eq("business_id", business_id)
            .eq("status", "active")
            .eq("agent_enabled", True)
            .ilike("name", f"%{term}%")
            .limit(bounded_limit)
        )
        for row in rows:
            rows_by_id.setdefault(str(row["id"]), row)
        if rows or len(rows_by_id) >= bounded_limit:
            break
    rows = list(rows_by_id.values())[:bounded_limit]
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


def _create_provider_model(
    settings: AgentRuntimeSettings,
    provider: str,
    *,
    vision: bool,
) -> Model | None:
    if provider == "google":
        api_key = settings.gemini_api_key
        if api_key is None:
            return None
        return GeminiModel(
            client_args={"api_key": api_key.get_secret_value()},
            model_id=settings.selected_model_id(vision=vision)
            if settings.agent_model_provider == provider
            else (
                settings.gemini_vision_model_id
                if vision
                else settings.gemini_model_id
            ),
            params={"max_output_tokens": MAX_AGENT_OUTPUT_TOKENS},
        )

    api_key = settings.openrouter_api_key
    if api_key is None:
        return None
    model_id = (
        settings.selected_model_id(vision=vision)
        if settings.agent_model_provider == provider
        else (
            settings.openrouter_vision_model_id
            if vision
            else settings.openrouter_model_id
        )
    )
    return OpenAIModel(
        client_args={
            "api_key": api_key.get_secret_value(),
            "base_url": "https://openrouter.ai/api/v1",
        },
        model_id=model_id,
        params={"max_tokens": MAX_AGENT_OUTPUT_TOKENS},
    )


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
    agent_run_id: str | None = None,
    created_checkout_urls: list[str] | None = None,
    checkout_errors: list[str] | None = None,
    selected_product_images: list[dict[str, Any]] | None = None,
    vision_enabled: bool = False,
) -> Agent:
    catalog_product_ids: dict[str, set[str]] = {}
    catalog_products: dict[str, dict[str, Any]] = {}

    def register_customer_catalog_products(
        products: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for product in products:
            product_id = str(product["product_id"])
            catalog_products[product_id] = product
            catalog_product_ids.setdefault(
                str(product["name"]).strip().casefold(), set()
            ).add(product_id)
        if audience == "customer":
            return [customer_catalog_product(product) for product in products]
        return products

    @tool
    def search_business_products(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Find active catalog products by name. Product IDs are internal and must never be shown to customers. The channel sends product photos only when the customer explicitly asks to see one."""
        products = find_business_products(client, business_id, query, limit)
        if audience == "customer":
            if selected_product_images is not None:
                selected_product_images[:] = [
                    {
                        "name": product["name"],
                        "image_urls": product.get("image_urls", []),
                    }
                    for product in products
                    if product.get("image_urls")
                ]
        return register_customer_catalog_products(products)

    @tool
    def list_available_business_products(limit: int = 8) -> list[dict[str, Any]]:
        """List active products that are enabled for the customer agent. Use this to check whether the catalog is available when the customer does not name a specific product or a name search returns no matches. An empty name search alone does not mean the catalog is empty."""
        if not 1 <= limit <= MAX_PRODUCT_SEARCH_RESULTS:
            raise ValueError(
                f"Product limit must be between 1 and {MAX_PRODUCT_SEARCH_RESULTS}."
            )
        rows = execute(
            client.table("products")
            .select(
                "id,name,description,price_minor,currency,stock_quantity,"
                "provider_data,image_asset_ids"
            )
            .eq("business_id", business_id)
            .eq("status", "active")
            .eq("agent_enabled", True)
            .order("updated_at", desc=True)
            .limit(limit)
        )
        products = [
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
        if audience == "customer" and selected_product_images is not None:
            selected_product_images[:] = [
                {"name": product["name"], "image_urls": product["image_urls"]}
                for product in products
                if product["image_urls"]
            ]
        return register_customer_catalog_products(products)

    @tool(inputSchema=CUSTOMER_ORDER_ITEMS_INPUT_SCHEMA)
    def calculate_customer_order_total(
        items: list[CustomerOrderItem],
    ) -> dict[str, Any]:
        """Calculate exact catalog prices and subtotals. Pass each item with the exact product_name from catalog results and an integer quantity. Example: {"items":[{"product_name":"Brown Vintage Shirt","quantity":2}]}. Do not use name, product, or item as the field name."""
        if not items or len(items) > 100:
            raise ValueError("Provide between 1 and 100 catalog items.")

        calculated_items: list[dict[str, Any]] = []
        subtotal_minor = 0
        currency: str | None = None
        for raw_item in items:
            item = CustomerOrderItem.model_validate(raw_item)
            matching_ids = catalog_product_ids.get(
                item.product_name.strip().casefold(), set()
            )
            if len(matching_ids) != 1:
                raise ValueError(
                    "Search for a specific catalog product before calculating its price."
                )

            product = catalog_products[next(iter(matching_ids))]
            product_currency = str(product["currency"]).upper()
            if currency is not None and product_currency != currency:
                raise ValueError("Items in one order must use the same currency.")
            currency = product_currency
            unit_price_minor = int(product["price_minor"])
            line_total_minor = unit_price_minor * item.quantity
            subtotal_minor += line_total_minor
            calculated_items.append(
                {
                    "product_name": product["name"],
                    "quantity": item.quantity,
                    "unit_price": format_minor_amount(
                        unit_price_minor, product_currency
                    ),
                    "line_total": format_minor_amount(
                        line_total_minor, product_currency
                    ),
                }
            )

        if currency is None:
            raise RuntimeError("The order subtotal could not be calculated.")
        return {
            "items": calculated_items,
            "item_subtotal": format_minor_amount(subtotal_minor, currency),
            "currency": currency,
            "note": "The secure checkout page shows the final amount.",
        }

    @tool
    def search_public_web(query: str) -> list[dict[str, str]]:
        """Search public web information when the business catalog does not answer the question."""
        return search_web(query)

    tools = [
        search_business_products,
        list_available_business_products,
        search_public_web,
    ]
    if audience == "customer":
        tools.append(calculate_customer_order_total)
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
    if audience == "owner":
        @tool
        def list_approval_requests(
            status_filter: str | None = None,
            limit: int = 10,
        ) -> list[dict[str, Any]]:
            """Read this business's recent approval requests and their current decisions. Use this before answering questions about whether a request was approved or declined."""
            allowed_statuses = {
                "pending",
                "approved",
                "rejected",
                "expired",
                "cancelled",
            }
            if status_filter is not None and status_filter not in allowed_statuses:
                raise ValueError("Choose a valid approval status.")
            if not 1 <= limit <= 50:
                raise ValueError("Approval request limit must be between 1 and 50.")

            query = (
                client.table("approvals")
                .select(
                    "id,action_type,status,impact,created_at,decided_at,decision_note"
                )
                .eq("business_id", business_id)
            )
            if status_filter is not None:
                query = query.eq("status", status_filter)
            rows = execute(query.order("created_at", desc=True).limit(limit))
            return rows if isinstance(rows, list) else []

        tools.append(list_approval_requests)
    if (
        audience == "customer"
        and conversation_id is not None
        and idempotency_key is not None
    ):
        @tool
        def request_customer_handoff(summary: str) -> dict[str, Any]:
            """Record a customer's explicit request for a team member to follow up when checkout needs human help. Only call this after the customer asks to buy or requests a person."""
            normalized_summary = summary.strip()
            if not normalized_summary or len(normalized_summary) > 2000:
                raise ValueError("Provide a handoff summary of 1 to 2000 characters.")

            request_key = (
                "customer-handoff:"
                + hashlib.sha256(idempotency_key.encode()).hexdigest()
            )
            existing = execute(
                client.table("approvals")
                .select("id,status,action_type,impact")
                .eq("business_id", business_id)
                .eq("request_idempotency_key", request_key)
                .maybe_single()
            )
            if existing is None:
                approval = execute(
                    client.table("approvals")
                    .insert(
                        {
                            "business_id": business_id,
                            "action_type": "customer_checkout_handoff",
                            "status": "pending",
                            "impact": {
                                "summary": normalized_summary,
                                "customer_name": customer_name[:160],
                                "conversation_id": conversation_id,
                            },
                            "expires_at": None,
                            "requested_by": "customer_agent",
                            "request_idempotency_key": request_key,
                        }
                    )
                    .select("id,status,action_type,impact")
                    .single()
                )
                if not isinstance(approval, dict):
                    raise RuntimeError("The customer handoff request could not be created.")
                execute(
                    client.table("outbox_events").insert(
                        {
                            "business_id": business_id,
                            "event_type": "approval.created",
                            "topic": "approvals",
                            "data": {"approval_id": approval["id"]},
                            "dedupe_key": f"approval-created:{approval['id']}",
                        }
                    )
                )
            else:
                approval = existing

            return {
                "approval_id": approval["id"],
                "status": approval["status"],
                "message": "The customer's request is recorded for team follow-up.",
            }

        tools.append(request_customer_handoff)
    if audience == "owner" and agent_run_id is not None:
        @tool
        def create_approval_request(
            action_type: str,
            summary: str,
            amount_minor: int | None = None,
            currency: str | None = None,
            customer_name: str | None = None,
            order_id: str | None = None,
        ) -> dict[str, Any]:
            """Create a pending approval request only when an authorized team member explicitly asks. This records a review request; approval does not perform the action."""
            normalized_action = re.sub(r"[^a-z0-9_]+", "_", action_type.strip().lower()).strip("_")
            normalized_summary = summary.strip()
            if not normalized_action or len(normalized_action) > 120:
                raise ValueError("Provide a short action type for the approval request.")
            if not normalized_summary or len(normalized_summary) > 2000:
                raise ValueError("Provide an approval summary of 1 to 2000 characters.")
            if amount_minor is not None and amount_minor < 0:
                raise ValueError("Approval amounts cannot be negative.")
            normalized_currency = currency.strip().upper() if currency else None
            if normalized_currency is not None and not re.fullmatch(
                r"[A-Z]{3}", normalized_currency
            ):
                raise ValueError("Provide a valid three-letter currency code.")

            impact: dict[str, Any] = {"summary": normalized_summary}
            if amount_minor is not None:
                impact["amount_minor"] = amount_minor
            if normalized_currency is not None:
                impact["currency"] = normalized_currency
            if customer_name and customer_name.strip():
                impact["customer_name"] = customer_name.strip()[:160]
            if order_id and order_id.strip():
                impact["order_id"] = order_id.strip()[:120]

            payload_hash = hashlib.sha256(
                f"{normalized_action}\n{normalized_summary}\n{impact}".encode()
            ).hexdigest()
            request_key = f"owner-agent:{agent_run_id}:{payload_hash}"
            existing = execute(
                client.table("approvals")
                .select("id,status,action_type,impact")
                .eq("business_id", business_id)
                .eq("request_idempotency_key", request_key)
                .maybe_single()
            )
            if existing is None:
                approval = execute(
                    client.table("approvals")
                    .insert(
                        {
                            "business_id": business_id,
                            "action_type": normalized_action,
                            "status": "pending",
                            "impact": impact,
                            "expires_at": None,
                            "requested_by": "business_agent",
                            "request_idempotency_key": request_key,
                        }
                    )
                    .select("id,status,action_type,impact")
                    .single()
                )
                if not isinstance(approval, dict):
                    raise RuntimeError("The approval request could not be created.")
                execute(
                    client.table("outbox_events").insert(
                        {
                            "business_id": business_id,
                            "event_type": "approval.created",
                            "topic": "approvals",
                            "data": {"approval_id": approval["id"]},
                            "dedupe_key": f"approval-created:{approval['id']}",
                        }
                    )
                )
            else:
                approval = existing

            return {
                "approval_id": approval["id"],
                "status": approval["status"],
                "action_type": approval["action_type"],
                "summary": approval["impact"].get("summary", normalized_summary),
                "message": "Approval request is queued for human review. Approval does not execute the action.",
            }

        tools.append(create_approval_request)
    checkout_tool_reasons: list[str] = []
    if audience == "customer":
        supabase_settings = get_supabase_settings()
        permissions = (agent_config or {}).get("permissions", {})
        if not supabase_settings.agentcard_enabled:
            checkout_tool_reasons.append("AGENTCARD_ENABLED_disabled")
        if not permissions.get("create_carts_and_orders"):
            checkout_tool_reasons.append("create_carts_and_orders_disabled")
        if not permissions.get("create_paypal_checkout"):
            checkout_tool_reasons.append("create_paypal_checkout_disabled")
        if conversation_id is None:
            checkout_tool_reasons.append("conversation_id_missing")
        if idempotency_key is None:
            checkout_tool_reasons.append("idempotency_key_missing")
        if created_checkout_urls is None:
            checkout_tool_reasons.append("checkout_url_collection_missing")
    if audience == "customer" and not checkout_tool_reasons:
        @tool(inputSchema=CUSTOMER_ORDER_ITEMS_INPUT_SCHEMA)
        def create_agentcard_transaction(
            items: list[CustomerOrderItem],
        ) -> dict[str, Any]:
            """Prepare secure checkout after the customer confirms the catalog items, quantities, and calculated total. Pass each item with exact product_name and integer quantity. Example: {"items":[{"product_name":"Brown Vintage Shirt","quantity":2}]}. Do not use name, product, or item as the field name."""
            validated_items = resolve_customer_checkout_items(
                items,
                catalog_product_ids,
            )
            try:
                result = create_agentcard_transaction_service(
                    client=client,
                    business_id=business_id,
                    conversation_id=conversation_id,
                    customer_name=customer_name,
                    customer_reference=customer_reference,
                    items=validated_items,
                    idempotency_key=idempotency_key,
                )
            except (HTTPException, ValueError) as error:
                error_code = (
                    error.detail.get("code", "http_error")
                    if isinstance(error, HTTPException)
                    and isinstance(error.detail, dict)
                    else "catalog_item_validation"
                    if isinstance(error, ValueError)
                    else "http_error"
                )
                logger.warning(
                    "AgentCard checkout creation failed business_id=%s error_code=%s",
                    business_id,
                    error_code,
                )
                if checkout_errors is not None:
                    checkout_errors.append(error_code)
                raise
            checkout_url = result["checkout_url"]
            created_checkout_urls.append(checkout_url)
            return {
                "transaction_id": result["public_transaction_id"],
                "checkout_url": checkout_url,
                "total": format_minor_amount(
                    result["snapshot"]["total_amount_minor"],
                    result["snapshot"]["currency"],
                ),
                "currency": result["snapshot"]["currency"],
                "expires_at": result["expires_at"],
                "status": result["status"],
            }

        tools.append(create_agentcard_transaction)
    elif audience == "customer":
        logger.info(
            "AgentCard checkout tool not registered business_id=%s reasons=%s",
            business_id,
            ",".join(checkout_tool_reasons),
        )

    fallback_provider = (
        "google" if settings.agent_model_provider != "google" else None
    )
    primary_model = _create_provider_model(
        settings,
        settings.agent_model_provider,
        vision=vision_enabled,
    )
    fallback_model = (
        _create_provider_model(settings, fallback_provider, vision=vision_enabled)
        if fallback_provider is not None
        else None
    )
    if primary_model is None and fallback_model is None:
        raise RuntimeError(
            "Configure GEMINI_API_KEY or OPENROUTER_API_KEY for the agent provider."
        )
    if primary_model is None:
        logger.warning(
            "Primary agent model provider has no API key; using fallback "
            "business_id=%s primary=%s fallback=%s",
            business_id,
            settings.agent_model_provider,
            fallback_provider,
        )
        model = fallback_model
    elif fallback_model is None or fallback_provider is None:
        model = primary_model
    else:
        model = FailoverModel(
            primary_model,
            fallback_model,
            primary_provider=settings.agent_model_provider,
            fallback_provider=fallback_provider,
            business_id=business_id,
        )

    system_prompt = build_business_system_prompt(
        business=business,
        agent_config=agent_config,
        audience=audience,
    )
    if audience == "customer" and checkout_tool_reasons:
        system_prompt += """

Checkout is not available in this conversation. Do not claim that a checkout
was created, that a team approval is required, or that a handoff was recorded
unless a tool result confirms it. Explain briefly that you cannot prepare a
secure checkout right now. Offer a team handoff only if one has not already been
recorded in the conversation. Do not repeatedly ask the customer to confirm the
same purchase.
"""
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
    try:
        result = agent(
            prompt,
            limits=Limits(
                turns=MAX_AGENT_TURNS,
                output_tokens=MAX_AGENT_OUTPUT_TOKENS,
                total_tokens=MAX_AGENT_TOTAL_TOKENS,
            ),
        )
    except MaxTokensReachedException:
        logger.warning(
            "Agent response reached its token limit; requesting a concise continuation"
        )
        try:
            result = agent(
                "Continue with one concise final response using completed tool results. "
                "Do not repeat actions that already succeeded.",
                limits=Limits(turns=2, output_tokens=400, total_tokens=2000),
            )
        except MaxTokensReachedException:
            logger.exception("Agent continuation also reached its token limit")
            if audience == "customer":
                return (
                    "I couldn't finish my reply just now because of a system limit. "
                    "Please try again or contact the store team."
                )
            raise
    response = str(result).strip()
    if not response:
        logger.error(
            "Agent returned no text after invocation audience=%s",
            audience,
        )
        if audience == "customer":
            return (
                "I couldn't complete that reply just now. Please try again, "
                "or contact the store team for help."
            )
        raise RuntimeError("The agent returned no text response.")
    response = sanitize_customer_response(response) if audience == "customer" else response
    return response[:10000]

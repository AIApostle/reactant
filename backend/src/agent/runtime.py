from typing import Any

import httpx

from strands import Agent, tool
from strands.models.openai import OpenAIModel
from strands.types.agent import Limits
from supabase import Client

from src.agent.config import AgentRuntimeSettings
from src.agent.prompts import build_business_system_prompt
from src.supabase.repository import execute


MAX_AGENT_TURNS = 6
MAX_AGENT_OUTPUT_TOKENS = 1200
MAX_AGENT_TOTAL_TOKENS = 8000
MAX_PRODUCT_SEARCH_RESULTS = 8
MAX_WEB_SEARCH_RESULTS = 5


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
        .select("name,description,price_minor,currency,stock_quantity")
        .eq("business_id", business_id)
        .eq("status", "active")
        .eq("agent_enabled", True)
        .ilike("name", f"%{escaped_query}%")
        .limit(bounded_limit)
    )
    return [
        {
            "name": row["name"],
            "description": (row.get("description") or "")[:500],
            "price_minor": row["price_minor"],
            "currency": row["currency"],
            "stock_quantity": row["stock_quantity"],
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
) -> Agent:
    @tool
    def search_business_products(query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Find active products in this business's catalog by product name."""
        return find_business_products(client, business_id, query, limit)

    @tool
    def search_public_web(query: str) -> list[dict[str, str]]:
        """Search public web information when the business catalog does not answer the question."""
        return search_web(query)

    if settings.openrouter_api_key is None:
        raise RuntimeError("The OpenRouter API key is not configured.")
    model = OpenAIModel(
        client_args={
            "api_key": settings.openrouter_api_key.get_secret_value(),
            "base_url": "https://openrouter.ai/api/v1",
        },
        model_id=settings.openrouter_model_id,
        params={"max_tokens": MAX_AGENT_OUTPUT_TOKENS},
    )

    system_prompt = build_business_system_prompt(
        business=business,
        agent_config=agent_config,
        audience=audience,
    )
    return Agent(
        model=model,
        tools=[search_business_products, search_public_web],
        system_prompt=system_prompt,
        messages=history,
    )


def invoke_business_agent(agent: Agent, message: str) -> str:
    result = agent(
        message,
        limits=Limits(
            turns=MAX_AGENT_TURNS,
            output_tokens=MAX_AGENT_OUTPUT_TOKENS,
            total_tokens=MAX_AGENT_TOTAL_TOKENS,
        ),
    )
    response = str(result).strip()
    if not response:
        raise RuntimeError("The agent returned no text response.")
    return response[:10000]

from typing import Any
from urllib.parse import urlparse

import httpx


class StorefrontError(Exception):
    pass


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            auth=auth,
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise StorefrontError from error


def _normalize_product(row: dict[str, Any], source: str) -> dict[str, Any]:
    price = row.get("price") or row.get("variants", [{}])[0].get("price") or "0"
    try:
        price_minor = round(float(price) * 100)
    except (TypeError, ValueError):
        price_minor = 0
    stock = row.get("stock_quantity")
    if stock is None and row.get("variants"):
        quantities = [variant.get("inventory_quantity") for variant in row["variants"]]
        numeric = [value for value in quantities if isinstance(value, int)]
        stock = sum(numeric) if numeric else None
    return {
        "source": source,
        "provider_product_id": str(row.get("id")),
        "name": str(row.get("name") or row.get("title") or "Unnamed product")[:255],
        "description": row.get("description") or row.get("body_html"),
        "category": row.get("categories", [{}])[0].get("name") if row.get("categories") else None,
        "price_minor": price_minor,
        "currency": str(row.get("currency") or "USD").upper()[:3],
        "stock_quantity": stock if isinstance(stock, int) and stock >= 0 else None,
        "status": "active" if row.get("status", "publish") in {"publish", "active"} else "draft",
        "agent_enabled": True,
        "provider_data": {"source": source, "provider_id": str(row.get("id"))},
    }


def test_woocommerce(store_url: str, consumer_key: str, consumer_secret: str) -> dict[str, Any]:
    base = store_url.rstrip("/")
    return _request(
        "GET",
        f"{base}/wp-json/wc/v3/system_status",
        auth=(consumer_key, consumer_secret),
    )


def sync_woocommerce(
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
) -> list[dict[str, Any]]:
    base = store_url.rstrip("/")
    rows = _request(
        "GET",
        f"{base}/wp-json/wc/v3/products",
        auth=(consumer_key, consumer_secret),
        params={"per_page": 100, "page": 1, "status": "publish"},
    )
    if not isinstance(rows, list):
        raise StorefrontError
    return [_normalize_product(row, "woocommerce") for row in rows if isinstance(row, dict)]


def _shop_domain(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"https://{value}")
    domain = parsed.netloc or parsed.path
    return domain.rstrip("/")


def test_shopify(shop_domain: str, access_token: str) -> dict[str, Any]:
    domain = _shop_domain(shop_domain)
    return _request(
        "GET",
        f"https://{domain}/admin/api/2025-10/shop.json",
        headers={"X-Shopify-Access-Token": access_token},
    )


def sync_shopify(shop_domain: str, access_token: str) -> list[dict[str, Any]]:
    domain = _shop_domain(shop_domain)
    payload = _request(
        "GET",
        f"https://{domain}/admin/api/2025-10/products.json",
        headers={"X-Shopify-Access-Token": access_token},
        params={"limit": 250, "status": "active"},
    )
    rows = payload.get("products", []) if isinstance(payload, dict) else []
    return [_normalize_product(row, "shopify") for row in rows if isinstance(row, dict)]

import asyncio
import unittest
from datetime import datetime, timezone
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr
from strands.models.openai import OpenAIModel

from src.agent import worker as agent_worker
from src.agent.config import AgentRuntimeSettings
from src.agent.runtime import (
    build_business_agent,
    customer_catalog_product,
    find_business_products,
    product_image_attachments,
    product_image_query,
    product_image_reply,
    resolve_customer_checkout_items,
    sanitize_customer_response,
)
from src.agent.prompts import build_business_system_prompt
from src.owner_assistant import routes as owner_assistant_routes
from src.catalog.routes import PRODUCT_FIELDS
from src.schemas.catalog import ProductResponse
from src.schemas.owner_assistant import OwnerMessageCreate
from src.schemas.workspace import BusinessResponse
from src.settings.routes import _business_response


class ProductQuery:
    def __init__(self) -> None:
        self.filters: list[tuple[str, tuple[object, ...]]] = []

    def select(self, fields: str) -> "ProductQuery":
        self.filters.append(("select", (fields,)))
        return self

    def eq(self, field: str, value: object) -> "ProductQuery":
        self.filters.append(("eq", (field, value)))
        return self

    def ilike(self, field: str, value: str) -> "ProductQuery":
        self.filters.append(("ilike", (field, value)))
        return self

    def limit(self, value: int) -> "ProductQuery":
        self.filters.append(("limit", (value,)))
        return self


class ProductClient:
    def __init__(self) -> None:
        self.query = ProductQuery()

    def table(self, name: str) -> ProductQuery:
        if name != "products":
            raise AssertionError(f"Unexpected table: {name}")
        return self.query


class OwnerAssistantRoutesTests(unittest.TestCase):
    def test_client_message_id_is_used_as_atomic_queue_key(self) -> None:
        user_id = uuid4()
        business_id = uuid4()
        thread_id = uuid4()
        message_id = uuid4()
        run_id = uuid4()
        client_message_id = uuid4()
        created_at = datetime.now(timezone.utc)
        request = owner_assistant_routes.Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [],
                "query_string": b"",
                "scheme": "http",
                "server": ("test", 80),
                "client": ("test", 80),
            }
        )
        request.state.request_id = "req_test"

        class FakeClient:
            def rpc(self, name: str, params: dict[str, object]) -> tuple[str, dict[str, object]]:
                return name, params

        rpc_result = {
            "message": {
                "id": str(message_id),
                "thread_id": str(thread_id),
                "sender_type": "user",
                "sender_id": str(user_id),
                "display_name": "Team member",
                "kind": "text",
                "text": "Check the latest product list.",
                "approval_id": None,
                "created_at": created_at.isoformat(),
                "read_at": None,
                "client_message_id": str(client_message_id),
                "agent_run_id": str(run_id),
            },
            "run": {"id": str(run_id), "status": "queued"},
        }

        rpc_requests: list[tuple[str, dict[str, object]]] = []

        def fake_execute(query: tuple[str, dict[str, object]]) -> dict[str, object]:
            rpc_requests.append(query)
            return rpc_result

        with (
            patch.object(
                owner_assistant_routes,
                "get_business_membership",
                return_value={"role": "owner"},
            ),
            patch.object(owner_assistant_routes, "require_role"),
            patch.object(owner_assistant_routes, "require_agent_runtime"),
            patch.object(
                owner_assistant_routes,
                "_owner_thread",
                return_value={"id": str(thread_id)},
            ),
            patch.object(owner_assistant_routes, "execute", side_effect=fake_execute),
        ):
            response = owner_assistant_routes.send_owner_message(
                business_id=business_id,
                body=OwnerMessageCreate(
                    text="Check the latest product list.",
                    client_message_id=client_message_id,
                ),
                request=request,
                user=owner_assistant_routes.AuthenticatedUser(
                    id=str(user_id),
                    email=None,
                    created_at=created_at,
                ),
                client=FakeClient(),
            )

        self.assertEqual(response.data.agent_run_id, run_id)
        self.assertEqual(response.data.agent_run_status, "queued")
        self.assertEqual(rpc_requests[0][0], "enqueue_owner_assistant_message")
        self.assertEqual(
            rpc_requests[0][1]["requested_idempotency_key"],
            str(client_message_id),
        )
        self.assertEqual(
            rpc_requests[0][1]["requested_client_message_id"],
            str(client_message_id),
        )

    def test_business_settings_response_drops_database_version(self) -> None:
        now = datetime.now(timezone.utc)
        row = {
            "id": str(uuid4()),
            "name": "Store",
            "country": "US",
            "currency": "USD",
            "timezone": "UTC",
            "support_email": None,
            "phone": None,
            "website": None,
            "return_policy": None,
            "delivery_policy": None,
            "created_at": now,
            "updated_at": now,
            "version": 4,
        }
        response = _business_response(row, "owner")
        self.assertIsInstance(response, BusinessResponse)
        self.assertNotIn("version", response.model_dump())


class AgentRuntimeTests(unittest.TestCase):
    def test_system_prompt_contains_business_context_and_safety_rules(self) -> None:
        prompt = build_business_system_prompt(
            business={
                "name": "Mina's Kitchen",
                "country": "NG",
                "currency": "NGN",
                "return_policy": "Returns within 7 days.",
                "delivery_policy": "Lagos delivery only.",
            },
            agent_config={
                "business_context": "We sell small-batch meals.",
                "tone": "friendly",
                "handoff_rule": "when_uncertain",
                "permissions": {"create_carts_and_orders": False},
                "approval_policy": {"require_approval_for_checkout": True},
            },
            audience="owner",
        )
        self.assertIn("Mina's Kitchen", prompt)
        self.assertIn("We sell small-batch meals.", prompt)
        self.assertIn("null stock quantity means stock is not tracked", prompt)
        self.assertIn("cannot mutate business data", prompt)
        self.assertIn("require_approval_for_checkout", prompt)
        customer_prompt = build_business_system_prompt(
            business={"name": "Store"},
            agent_config=None,
            audience="customer",
        )
        self.assertIn("matching catalog images automatically when available", customer_prompt)
        self.assertIn("even when the customer did not explicitly", customer_prompt)

    def test_agent_has_only_the_scoped_catalog_tool(self) -> None:
        with patch("src.agent.runtime.get_memory_config", return_value=None):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(openrouter_api_key=SecretStr("test-key")),
                business={"name": "Store", "country": "US", "currency": "USD"},
                agent_config=None,
                history=[],
            )
        self.assertEqual(
            sorted(agent.tool_registry.registry.keys()),
            ["search_business_products", "search_public_web"],
        )

    def test_customer_memory_tools_are_not_registered_without_opt_in(self) -> None:
        with (
            patch("src.agent.runtime.get_memory_config") as get_memory,
            patch(
                "src.agent.runtime.get_supabase_settings",
                return_value=SimpleNamespace(agentcard_enabled=False),
            ),
        ):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(openrouter_api_key=SecretStr("test-key")),
                business={"name": "Store", "country": "US", "currency": "USD"},
                agent_config=None,
                history=[],
                audience="customer",
                memory_customer_reference="visitor-1",
                memory_opt_in=False,
            )

        get_memory.assert_not_called()
        self.assertNotIn("search_business_memory", agent.tool_registry.registry)
        self.assertNotIn("remember_business_fact", agent.tool_registry.registry)

    def test_product_image_query_uses_recent_product_when_customer_is_vague(self) -> None:
        query = product_image_query(
            "Can I see a picture of the product you guys have (my message)?",
            [
                {"sender_type": "customer", "text": "Do you have shoes?"},
                {"sender_type": "agent", "text": "We have Shoes in the catalog."},
            ],
        )
        self.assertEqual(query, "shoes")

    def test_product_image_delivery_is_confirmed_only_after_attachment_exists(self) -> None:
        product = {
            "name": "Canvas bag",
            "image_urls": ["https://storage.example/photo.png"],
        }
        attachments = product_image_attachments(
            [product],
            "The Canvas bag is a good choice.",
            explicitly_requested=False,
        )
        self.assertEqual(attachments[0]["alt"], "Canvas bag")
        self.assertIn("included a photo", product_image_reply("Recommended.", attachments, explicitly_requested=False))
        self.assertIn("couldn't send", product_image_reply("Recommended.", [], explicitly_requested=True, delivery_failed=True))
        self.assertIn("couldn't find", product_image_reply("Recommended.", [], explicitly_requested=True))

    def test_customer_catalog_result_does_not_expose_internal_product_id_or_image_url(self) -> None:
        result = customer_catalog_product(
            {
                "product_id": "d7356ad3-ba69-46fd-91d1-daebf6ab7142",
                "name": "Shoes",
                "description": "Canvas shoes",
                "price_minor": 100,
                "currency": "USD",
                "stock_quantity": 20,
                "image_urls": ["https://storage.example/private-photo.png"],
            }
        )

        self.assertNotIn("product_id", result)
        self.assertNotIn("image_urls", result)
        self.assertTrue(result["image_available"])
        self.assertEqual(result["name"], "Shoes")

    def test_customer_checkout_resolves_only_products_from_catalog_search(self) -> None:
        items = resolve_customer_checkout_items(
            [{"product_name": "Shoes", "quantity": 2}],
            {"shoes": {"d7356ad3-ba69-46fd-91d1-daebf6ab7142"}},
        )

        self.assertEqual(str(items[0].product_id), "d7356ad3-ba69-46fd-91d1-daebf6ab7142")
        self.assertEqual(items[0].quantity, 2)

    def test_customer_checkout_rejects_ambiguous_names_and_untrusted_ids(self) -> None:
        with self.assertRaises(ValueError):
            resolve_customer_checkout_items(
                [{"product_name": "Shoes", "quantity": 1}],
                {"shoes": {"product-id-a", "product-id-b"}},
            )
        with self.assertRaises(ValueError):
            resolve_customer_checkout_items(
                [{"product_id": "d7356ad3-ba69-46fd-91d1-daebf6ab7142", "quantity": 1}],
                {"shoes": {"d7356ad3-ba69-46fd-91d1-daebf6ab7142"}},
            )

    def test_customer_response_sanitizer_removes_internal_product_ids(self) -> None:
        response = sanitize_customer_response(
            "Shoes (product_id: d7356ad3-ba69-46fd-91d1-daebf6ab7142)."
        )
        self.assertNotIn("d7356ad3-ba69-46fd-91d1-daebf6ab7142", response)
        self.assertNotIn("product ID", response)

    def test_agent_uses_openrouter_free_model_with_configured_api_key(self) -> None:
        settings = AgentRuntimeSettings(openrouter_api_key=SecretStr("test-key"))
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store", "country": "US", "currency": "USD"},
            agent_config=None,
            history=[],
        )

        self.assertIsInstance(agent.model, OpenAIModel)
        self.assertEqual(agent.model.config["model_id"], "openrouter/free")
        self.assertEqual(
            agent.model.client_args["base_url"],
            "https://openrouter.ai/api/v1",
        )
        self.assertEqual(agent.model.client_args["api_key"], "test-key")

    def test_agent_uses_vision_model_for_customer_image_messages(self) -> None:
        settings = AgentRuntimeSettings(
            openrouter_api_key=SecretStr("test-key"),
            openrouter_vision_model_id="test/vision-model",
        )
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store", "country": "US", "currency": "USD"},
            agent_config=None,
            history=[],
            audience="customer",
            vision_enabled=True,
        )
        self.assertEqual(agent.model.config["model_id"], "test/vision-model")

    def test_product_search_is_tenant_scoped_and_limits_returned_fields(self) -> None:
        client = ProductClient()
        rows = [
            {
                "id": "product-a",
                "name": "Canvas bag",
                "description": "Reusable bag",
                "price_minor": 2500,
                "currency": "USD",
                "stock_quantity": 3,
                "provider_data": {"private": "not returned"},
            }
        ]
        with patch("src.agent.runtime.execute", return_value=rows):
            products = find_business_products(
                client,
                "business-a",
                "bag%_",
                limit=100,
            )

        self.assertEqual(
            products,
            [
                {
                    "product_id": "product-a",
                    "name": "Canvas bag",
                    "description": "Reusable bag",
                    "price_minor": 2500,
                    "currency": "USD",
                    "stock_quantity": 3,
                    "image_urls": [],
                }
            ],
        )
        self.assertIn(("eq", ("business_id", "business-a")), client.query.filters)
        self.assertIn(("eq", ("status", "active")), client.query.filters)
        self.assertIn(("eq", ("agent_enabled", True)), client.query.filters)
        self.assertIn(("ilike", ("name", "%bag\\%\\_%")), client.query.filters)
        self.assertIn(("limit", (8,)), client.query.filters)

    def test_product_response_projection_excludes_database_only_fields(self) -> None:
        self.assertNotIn("provider_product_id", PRODUCT_FIELDS)
        self.assertNotIn("provider_data", PRODUCT_FIELDS)
        self.assertEqual(set(PRODUCT_FIELDS.split(",")), {
            field for field in ProductResponse.model_fields if field != "image_urls"
        })


class AgentWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_execution_runs_off_the_request_event_loop(self) -> None:
        run = {"id": "run-id"}
        with (
            patch.object(
                agent_worker,
                "_process_run",
                side_effect=lambda _client, _run: sleep(0.05),
            ),
            patch.object(agent_worker, "_heartbeat", return_value=True) as heartbeat,
            patch.object(agent_worker, "AGENT_RUN_HEARTBEAT_SECONDS", 0.005),
        ):
            processing = asyncio.create_task(
                agent_worker._process_with_heartbeat(object(), run)
            )
            await asyncio.sleep(0.015)
            self.assertFalse(processing.done())
            await processing

        self.assertGreater(heartbeat.call_count, 0)


if __name__ == "__main__":
    unittest.main()

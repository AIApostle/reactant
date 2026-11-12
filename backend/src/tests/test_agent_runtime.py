import asyncio
import os
import unittest
from datetime import datetime, timezone
from time import sleep
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import SecretStr
from strands.models.gemini import GeminiModel
from strands.models.openai import OpenAIModel
from strands.types.exceptions import MaxTokensReachedException, ModelThrottledException

from src.agent import worker as agent_worker
from src.agent.config import AgentRuntimeSettings
from src.agent.runtime import (
    FailoverModel,
    build_business_agent,
    customer_catalog_product,
    find_business_products,
    include_secure_checkout_link,
    invoke_business_agent,
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
    def test_google_api_key_environment_names_are_supported(self) -> None:
        for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            with self.subTest(key_name=key_name), patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "AGENT_MODEL_PROVIDER": "google",
                    key_name: "test-google-key",
                },
                clear=True,
            ):
                settings = AgentRuntimeSettings(_env_file=None)

            self.assertEqual(settings.agent_model_provider, "google")
            self.assertEqual(settings.model_api_key.get_secret_value(), "test-google-key")
            self.assertEqual(settings.required_api_key_name, "GEMINI_API_KEY")

    def test_google_is_default_agent_provider(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = AgentRuntimeSettings(_env_file=None)

        self.assertEqual(settings.agent_model_provider, "google")
        self.assertEqual(settings.required_api_key_name, "GEMINI_API_KEY")
        self.assertEqual(settings.selected_model_id(), "gemini-3.6-flash")

    def test_retired_gemini_model_setting_is_upgraded(self) -> None:
        settings = AgentRuntimeSettings(
            agent_model_provider="google",
            gemini_model_id="gemini-2.5-flash",
            gemini_vision_model_id="gemini-3.8-flash",
        )

        self.assertEqual(settings.selected_model_id(), "gemini-3.6-flash")
        self.assertEqual(settings.selected_model_id(vision=True), "gemini-3.6-flash")

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
        self.assertIn("cannot contact customers", prompt)
        self.assertIn("require_approval_for_checkout", prompt)
        customer_prompt = build_business_system_prompt(
            business={"name": "Store"},
            agent_config=None,
            audience="customer",
        )
        self.assertIn("matching catalog images automatically when available", customer_prompt)
        self.assertIn("Do not send product photos", customer_prompt)
        self.assertIn("explicitly asks to see a photo", customer_prompt)
        self.assertIn("list_available_business_products", customer_prompt)
        self.assertIn("calculate_customer_order_total", customer_prompt)
        self.assertIn('"product_name": "Exact catalog product name"', customer_prompt)
        self.assertIn("Never calculate, estimate, round, convert currencies, or", customer_prompt)
        self.assertIn("ask the customer", customer_prompt)
        self.assertIn("Do not create checkout until they confirm", customer_prompt)
        self.assertIn(
            "expected to help complete checkout",
            " ".join(customer_prompt.split()),
        )
        owner_prompt = build_business_system_prompt(
            business={"name": "Store"},
            agent_config=None,
            audience="owner",
        )
        self.assertIn("create_approval_request", owner_prompt)
        self.assertIn("approval does not execute", owner_prompt)

    def test_agent_has_only_the_scoped_catalog_tool(self) -> None:
        with patch("src.agent.runtime.get_memory_config", return_value=None):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store", "country": "US", "currency": "USD"},
                agent_config=None,
                history=[],
                audience="customer",
            )
        self.assertEqual(
            sorted(agent.tool_registry.registry.keys()),
            [
                "calculate_customer_order_total",
                "list_available_business_products",
                "search_business_products",
                "search_public_web",
            ],
        )

    def test_customer_agent_can_list_agent_visible_products(self) -> None:
        product = {
            "id": str(uuid4()),
            "name": "Grey Vintage Shirt",
            "description": "Vintage cotton shirt",
            "price_minor": 500,
            "currency": "USD",
            "stock_quantity": 4,
            "provider_data": {"image_urls": ["https://cdn.example.com/shirt.jpg"]},
            "image_asset_ids": [],
        }
        client = MagicMock()
        selected_images: list[dict[str, Any]] = []
        checkout_urls: list[str] = []
        with (
            patch("src.agent.runtime.get_memory_config", return_value=None),
            patch(
                "src.agent.runtime.get_supabase_settings",
                return_value=SimpleNamespace(agentcard_enabled=True),
            ),
            patch("src.agent.runtime.execute", return_value=[product]),
            patch(
                "src.agent.runtime.create_agentcard_transaction_service",
                return_value={
                    "checkout_url": "https://checkout.example.com/session",
                    "public_transaction_id": "transaction-a",
                    "snapshot": {
                        "total_amount_minor": 1000,
                        "currency": "USD",
                    },
                    "expires_at": "2026-11-12T00:00:00+00:00",
                    "status": "pending",
                },
            ) as create_transaction,
        ):
            agent = build_business_agent(
                client=client,
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store"},
                agent_config={
                    "permissions": {
                        "create_carts_and_orders": True,
                        "create_paypal_checkout": True,
                    }
                },
                history=[],
                audience="customer",
                conversation_id="conversation-a",
                idempotency_key="telegram:update-a",
                created_checkout_urls=checkout_urls,
                selected_product_images=selected_images,
            )
            products = agent.tool_registry.registry[
                "list_available_business_products"
            ]._tool_func(limit=8)
            calculator_tool = agent.tool_registry.registry[
                "calculate_customer_order_total"
            ]
            item_schema = calculator_tool.tool_spec["inputSchema"]["json"][
                "properties"
            ]["items"]["items"]
            validated_calculator_input = calculator_tool._metadata.validate_input(
                {
                    "items": [
                        {
                            "product_name": "Grey Vintage Shirt",
                            "quantity": 2,
                        }
                    ]
                }
            )
            with self.assertRaises(ValueError):
                calculator_tool._metadata.validate_input(
                    {
                        "items": [
                            {"name": "Grey Vintage Shirt", "quantity": 2}
                        ]
                    }
                )
            checkout_item_schema = agent.tool_registry.registry[
                "create_agentcard_transaction"
            ].tool_spec["inputSchema"]["json"]["properties"]["items"]["items"]
            total = agent.tool_registry.registry[
                "calculate_customer_order_total"
            ]._tool_func(
                items=[
                    {"product_name": "Grey Vintage Shirt", "quantity": 2}
                ]
            )
            with self.assertRaises(ValueError):
                agent.tool_registry.registry[
                    "list_available_business_products"
                ]._tool_func(limit=9)
            checkout = agent.tool_registry.registry[
                "create_agentcard_transaction"
            ]._tool_func(
                items=[{"product_name": "Grey Vintage Shirt", "quantity": 1}]
            )

        self.assertEqual(products[0]["name"], "Grey Vintage Shirt")
        self.assertNotIn("product_id", products[0])
        self.assertNotIn("price_minor", products[0])
        self.assertEqual(products[0]["unit_price"], "USD 5.00")
        self.assertEqual(
            item_schema["required"],
            ["product_name", "quantity"],
        )
        self.assertIn("product_name", item_schema["properties"])
        self.assertIn("quantity", item_schema["properties"])
        self.assertEqual(item_schema, checkout_item_schema)
        self.assertEqual(
            validated_calculator_input["items"][0],
            {"product_name": "Grey Vintage Shirt", "quantity": 2},
        )
        self.assertEqual(total["items"][0]["line_total"], "USD 10.00")
        self.assertEqual(total["item_subtotal"], "USD 10.00")
        self.assertEqual(
            selected_images,
            [
                {
                    "name": "Grey Vintage Shirt",
                    "image_urls": ["https://cdn.example.com/shirt.jpg"],
                }
            ],
        )
        self.assertEqual(
            checkout["checkout_url"], "https://checkout.example.com/session"
        )
        self.assertEqual(checkout["total"], "USD 10.00")
        self.assertEqual(checkout_urls, ["https://checkout.example.com/session"])
        self.assertEqual(
            str(create_transaction.call_args.kwargs["items"][0].product_id),
            product["id"],
        )
        query = client.table.return_value.select.return_value
        query.eq.assert_called_once_with("business_id", "business-a")
        query.eq.return_value.eq.assert_called_once_with("status", "active")
        query.eq.return_value.eq.return_value.eq.assert_called_once_with(
            "agent_enabled", True
        )

    def test_owner_agent_run_has_approval_request_tool(self) -> None:
        with patch("src.agent.runtime.get_memory_config", return_value=None):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store", "country": "US", "currency": "USD"},
                agent_config=None,
                history=[],
                audience="owner",
                agent_run_id="run-a",
            )

        self.assertIn("create_approval_request", agent.tool_registry.registry)
        self.assertIn("list_approval_requests", agent.tool_registry.registry)

    def test_owner_agent_can_read_current_approval_status(self) -> None:
        approved_row = {
            "id": str(uuid4()),
            "action_type": "customer_checkout_handoff",
            "status": "approved",
            "impact": {"summary": "Grey Vintage Shirt, quantity 2"},
            "created_at": "2026-11-11T23:00:00+00:00",
            "decided_at": "2026-11-11T23:10:00+00:00",
            "decision_note": None,
        }
        client = MagicMock()
        with (
            patch("src.agent.runtime.get_memory_config", return_value=None),
            patch("src.agent.runtime.execute", return_value=[approved_row]),
        ):
            agent = build_business_agent(
                client=client,
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store"},
                agent_config=None,
                history=[],
                audience="owner",
            )
            approvals = agent.tool_registry.registry[
                "list_approval_requests"
            ]._tool_func(status_filter="approved")

        self.assertEqual(approvals, [approved_row])
        client.table.assert_called_with("approvals")
        query = client.table.return_value.select.return_value
        query.eq.assert_called_once_with("business_id", "business-a")
        query.eq.return_value.eq.assert_called_once_with("status", "approved")

    def test_owner_agent_can_create_an_idempotent_approval_request(self) -> None:
        approval_id = str(uuid4())
        created_approval = {
            "id": approval_id,
            "status": "pending",
            "action_type": "issue_refund",
            "impact": {"summary": "Refund order 42", "amount_minor": 1250, "currency": "USD"},
        }
        client = MagicMock()
        with (
            patch("src.agent.runtime.get_memory_config", return_value=None),
            patch(
                "src.agent.runtime.execute",
                side_effect=[None, created_approval, None],
            ) as execute_query,
        ):
            agent = build_business_agent(
                client=client,
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store"},
                agent_config=None,
                history=[],
                audience="owner",
                agent_run_id="run-a",
            )
            result = agent.tool_registry.registry[
                "create_approval_request"
            ]._tool_func(
                action_type="issue refund",
                summary="Refund order 42",
                amount_minor=1250,
                currency="usd",
            )

        self.assertEqual(result["approval_id"], approval_id)
        self.assertEqual(result["status"], "pending")
        self.assertIn("does not execute", result["message"])
        self.assertEqual(execute_query.call_count, 3)
        inserted_approval = client.table.return_value.insert.call_args_list[0].args[0]
        self.assertEqual(inserted_approval["requested_by"], "business_agent")
        self.assertEqual(inserted_approval["impact"]["amount_minor"], 1250)
        inserted_outbox_event = client.table.return_value.insert.call_args_list[1].args[0]
        self.assertEqual(inserted_outbox_event["event_type"], "approval.created")

    def test_customer_agent_registers_agentcard_checkout_when_enabled(self) -> None:
        with patch(
            "src.agent.runtime.get_supabase_settings",
            return_value=SimpleNamespace(agentcard_enabled=True),
        ), patch("src.agent.runtime.get_memory_config", return_value=None):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store", "country": "US", "currency": "USD"},
                agent_config={
                    "permissions": {
                        "create_carts_and_orders": True,
                        "create_paypal_checkout": True,
                    }
                },
                history=[],
                audience="customer",
                conversation_id="conversation-a",
                idempotency_key="website:message-a",
                created_checkout_urls=[],
            )

        self.assertIn("create_agentcard_transaction", agent.tool_registry.registry)

    def test_customer_agent_logs_checkout_tool_gate_reasons(self) -> None:
        with (
            patch(
                "src.agent.runtime.get_supabase_settings",
                return_value=SimpleNamespace(agentcard_enabled=False),
            ),
            patch("src.agent.runtime.get_memory_config", return_value=None),
            self.assertLogs("src.agent.runtime", level="INFO") as logs,
        ):
            agent = build_business_agent(
                client=ProductClient(),
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store"},
                agent_config={"permissions": {}},
                history=[],
                audience="customer",
                conversation_id="conversation-a",
                idempotency_key="telegram:update-a",
                created_checkout_urls=[],
            )

        self.assertNotIn("create_agentcard_transaction", agent.tool_registry.registry)
        self.assertIn("AGENTCARD_ENABLED_disabled", logs.output[0])
        self.assertIn("create_carts_and_orders_disabled", logs.output[0])
        self.assertIn("create_paypal_checkout_disabled", logs.output[0])
        self.assertIn("Checkout is not available", agent.system_prompt)

    def test_customer_agent_records_checkout_handoff_as_pending_approval(self) -> None:
        approval_id = str(uuid4())
        created_approval = {
            "id": approval_id,
            "status": "pending",
            "action_type": "customer_checkout_handoff",
            "impact": {"summary": "Grey Vintage Shirt, quantity 2"},
        }
        client = MagicMock()
        with (
            patch(
                "src.agent.runtime.get_supabase_settings",
                return_value=SimpleNamespace(agentcard_enabled=False),
            ),
            patch("src.agent.runtime.get_memory_config", return_value=None),
            patch(
                "src.agent.runtime.execute",
                side_effect=[None, created_approval, None, created_approval],
            ) as execute_query,
        ):
            agent = build_business_agent(
                client=client,
                business_id="business-a",
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
                business={"name": "Store"},
                agent_config={"permissions": {}},
                history=[],
                audience="customer",
                conversation_id="conversation-a",
                customer_name="Acha",
                idempotency_key="telegram:update-a",
            )
            result = agent.tool_registry.registry[
                "request_customer_handoff"
            ]._tool_func(summary="Grey Vintage Shirt, quantity 2")
            repeated_result = agent.tool_registry.registry[
                "request_customer_handoff"
            ]._tool_func(summary="Grey Vintage Shirt, quantity 2")

        self.assertEqual(result["approval_id"], approval_id)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(repeated_result["approval_id"], approval_id)
        self.assertEqual(execute_query.call_count, 4)
        self.assertEqual(client.table.return_value.insert.call_count, 2)
        inserted_approval = client.table.return_value.insert.call_args_list[0].args[0]
        self.assertEqual(inserted_approval["action_type"], "customer_checkout_handoff")
        self.assertEqual(inserted_approval["requested_by"], "customer_agent")
        self.assertEqual(inserted_approval["impact"]["customer_name"], "Acha")
        self.assertEqual(inserted_approval["impact"]["conversation_id"], "conversation-a")
        inserted_event = client.table.return_value.insert.call_args_list[1].args[0]
        self.assertEqual(inserted_event["event_type"], "approval.created")

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
                settings=AgentRuntimeSettings(
                    agent_model_provider="openrouter",
                    openrouter_api_key=SecretStr("test-key"),
                ),
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

    def test_product_images_are_only_attached_when_explicitly_requested(self) -> None:
        product = {
            "name": "Canvas bag",
            "image_urls": ["https://storage.example/photo.png"],
        }
        self.assertEqual(
            product_image_attachments(
                [product],
                explicitly_requested=False,
            ),
            [],
        )
        attachments = product_image_attachments([product], explicitly_requested=True)
        self.assertEqual(attachments[0]["alt"], "Canvas bag")
        self.assertIn(
            "couldn't send",
            product_image_reply(
                "Recommended.", [], explicitly_requested=True, delivery_failed=True
            ),
        )
        self.assertIn(
            "couldn't find",
            product_image_reply("Recommended.", [], explicitly_requested=True),
        )

    def test_checkout_link_is_appended_once_after_customer_response(self) -> None:
        url = "https://getreactant.vercel.app/checkout/example"

        self.assertEqual(
            include_secure_checkout_link("Your checkout is ready.", [url]),
            f"Your checkout is ready.\n\nSecure checkout: {url}",
        )
        self.assertEqual(
            include_secure_checkout_link(f"Secure checkout: {url}", [url]),
            f"Secure checkout: {url}",
        )

    def test_customer_prompt_does_not_allow_unsolicited_product_photos(self) -> None:
        prompt = build_business_system_prompt(
            business={"name": "Store"},
            agent_config=None,
            audience="customer",
        )

        self.assertIn("Do not send product photos", prompt)
        self.assertIn(
            "image availability alone is not a reason to send one",
            " ".join(prompt.split()),
        )

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
        self.assertNotIn("price_minor", result)
        self.assertEqual(result["unit_price"], "USD 1.00")
        self.assertEqual(result["name"], "Shoes")

    def test_agent_continues_concisely_after_token_limit(self) -> None:
        calls: list[tuple[str, Any]] = []

        def fake_agent(message: str, *, limits: Any) -> str:
            calls.append((message, limits))
            if len(calls) == 1:
                raise MaxTokensReachedException("limit reached")
            return "I couldn't prepare checkout right now."

        response = invoke_business_agent(
            fake_agent, "Can we check out?", audience="customer"
        )

        self.assertEqual(response, "I couldn't prepare checkout right now.")
        self.assertEqual(len(calls), 2)
        self.assertIn("Do not repeat actions", calls[1][0])

    def test_customer_agent_returns_explicit_message_if_model_returns_no_text(self) -> None:
        response = invoke_business_agent(
            lambda *_args, **_kwargs: "",
            "Can we check out?",
            audience="customer",
        )

        self.assertIn("couldn't complete that reply", response)

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

    def test_customer_checkout_rejects_wrong_item_field_names(self) -> None:
        with self.assertRaises(ValueError):
            resolve_customer_checkout_items(
                [{"name": "Brown Vintage Shirt", "quantity": 2}],
                {"brown vintage shirt": {"d7356ad3-ba69-46fd-91d1-daebf6ab7142"}},
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
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="openrouter",
            openrouter_api_key=SecretStr("test-key"),
        )
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

    def test_agent_uses_native_gemini_model_when_selected(self) -> None:
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="google",
            gemini_api_key=SecretStr("test-key"),
        )
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store", "country": "US", "currency": "USD"},
            agent_config=None,
            history=[],
        )

        self.assertIsInstance(agent.model, GeminiModel)
        self.assertEqual(agent.model.config["model_id"], "gemini-3.6-flash")
        self.assertEqual(agent.model.client_args["api_key"], "test-key")

    def test_agent_configures_openrouter_to_gemini_failover(self) -> None:
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="openrouter",
            openrouter_api_key=SecretStr("openrouter-key"),
            gemini_api_key=SecretStr("gemini-key"),
        )
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store"},
            agent_config=None,
            history=[],
        )

        self.assertIsInstance(agent.model, FailoverModel)
        self.assertIsInstance(agent.model.primary, OpenAIModel)
        self.assertIsInstance(agent.model.fallback, GeminiModel)

    def test_agent_configures_gemini_to_openrouter_failover(self) -> None:
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="google",
            gemini_api_key=SecretStr("gemini-key"),
            openrouter_api_key=SecretStr("openrouter-key"),
        )
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store"},
            agent_config=None,
            history=[],
        )

        self.assertIsInstance(agent.model, FailoverModel)
        self.assertIsInstance(agent.model.primary, GeminiModel)
        self.assertIsInstance(agent.model.fallback, OpenAIModel)

    def test_agent_uses_fallback_when_primary_key_is_missing(self) -> None:
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="google",
            openrouter_api_key=SecretStr("openrouter-key"),
        )
        agent = build_business_agent(
            client=ProductClient(),
            business_id="business-a",
            settings=settings,
            business={"name": "Store"},
            agent_config=None,
            history=[],
        )

        self.assertIsInstance(agent.model, OpenAIModel)

    def test_failover_discards_partial_primary_stream_before_retry(self) -> None:
        class FakeModel:
            def __init__(self, events: list[dict[str, Any]], error: Exception | None = None):
                self.events = events
                self.error = error

            async def stream(self, *args: Any, **kwargs: Any):
                for event in self.events:
                    yield event
                if self.error is not None:
                    raise self.error

            def get_config(self) -> dict[str, str]:
                return {"model_id": "fake"}

            def update_config(self, **model_config: Any) -> None:
                pass

            async def structured_output(self, *args: Any, **kwargs: Any):
                if False:
                    yield {}

        primary_partial = {"contentBlockDelta": {"delta": {"text": "partial"}}}
        fallback_result = {"contentBlockDelta": {"delta": {"text": "fallback"}}}
        model = FailoverModel(
            FakeModel([primary_partial], ModelThrottledException("temporarily limited")),
            FakeModel([fallback_result]),
            primary_provider="google",
            fallback_provider="openrouter",
            business_id="business-a",
        )

        async def collect() -> list[dict[str, Any]]:
            return [event async for event in model.stream([])]

        self.assertEqual(asyncio.run(collect()), [fallback_result])

    def test_agent_uses_vision_model_for_customer_image_messages(self) -> None:
        settings = AgentRuntimeSettings(
            _env_file=None,
            agent_model_provider="openrouter",
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
        model = agent.model.primary if isinstance(agent.model, FailoverModel) else agent.model
        self.assertEqual(model.config["model_id"], "test/vision-model")

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

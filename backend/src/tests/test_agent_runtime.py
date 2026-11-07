import asyncio
import unittest
from datetime import datetime, timezone
from time import sleep
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr
from strands.models.openai import OpenAIModel

from src.agent import worker as agent_worker
from src.agent.config import AgentRuntimeSettings
from src.agent.runtime import build_business_agent, find_business_products
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
    def test_agent_has_only_the_scoped_catalog_tool(self) -> None:
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

    def test_product_search_is_tenant_scoped_and_limits_returned_fields(self) -> None:
        client = ProductClient()
        rows = [
            {
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
                    "name": "Canvas bag",
                    "description": "Reusable bag",
                    "price_minor": 2500,
                    "currency": "USD",
                    "stock_quantity": 3,
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
        self.assertEqual(
            set(PRODUCT_FIELDS.split(",")),
            set(ProductResponse.model_fields),
        )


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

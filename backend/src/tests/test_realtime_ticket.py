import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi import HTTPException

from src.realtime.routes import create_realtime_ticket
from src.schemas.agentcard import AgentCardManualCheckoutRequest
from src.agentcard.routes import create_agentcard_test_checkout


class RealtimeTicketTests(unittest.TestCase):
    def test_ticket_uses_membership_checked_rpc_and_keeps_response(self) -> None:
        business_id = UUID("ec1bdf46-3672-443a-b3d6-0d8c1252ddac")
        user_id = UUID("6ae108fb-138b-4ce8-84cf-c42cb80926ac")
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="https", netloc="api.example.com"),
            state=SimpleNamespace(request_id="request-id"),
        )
        client = MagicMock()
        user = SimpleNamespace(id=user_id)

        with (
            patch("src.realtime.routes.get_business_membership"),
            patch("src.realtime.routes.execute") as execute,
        ):
            response = create_realtime_ticket(
                business_id,
                request,
                user,
                client,
            )

        args, _ = execute.call_args
        self.assertEqual(args[0], client.rpc.return_value)
        client.rpc.assert_called_once()
        self.assertEqual(client.rpc.call_args.args[0], "create_realtime_ticket")
        self.assertEqual(response.data.websocket_url, "wss://api.example.com/api/v1/realtime/ws")
        self.assertTrue(response.data.ticket)

    def test_ticket_returns_specific_code_when_rpc_migration_is_missing(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="https", netloc="api.example.com"),
            state=SimpleNamespace(request_id="request-id"),
        )
        with (
            patch("src.realtime.routes.get_business_membership"),
            patch(
                "src.realtime.routes.execute",
                side_effect=HTTPException(status_code=403, detail={"code": "not_authorized"}),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_realtime_ticket(
                UUID("ec1bdf46-3672-443a-b3d6-0d8c1252ddac"),
                request,
                SimpleNamespace(id=UUID("6ae108fb-138b-4ce8-84cf-c42cb80926ac")),
                MagicMock(),
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            raised.exception.detail["code"],
            "realtime_ticket_database_migration_required",
        )

    def test_ticket_returns_specific_code_when_rpc_is_missing_from_schema_cache(self) -> None:
        request = SimpleNamespace(
            url=SimpleNamespace(scheme="https", netloc="api.example.com"),
            state=SimpleNamespace(request_id="request-id"),
        )
        with (
            patch("src.realtime.routes.get_business_membership"),
            patch(
                "src.realtime.routes.execute",
                side_effect=HTTPException(
                    status_code=503,
                    detail={"code": "database_schema_outdated"},
                ),
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            create_realtime_ticket(
                UUID("ec1bdf46-3672-443a-b3d6-0d8c1252ddac"),
                request,
                SimpleNamespace(id=UUID("6ae108fb-138b-4ce8-84cf-c42cb80926ac")),
                MagicMock(),
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            raised.exception.detail["code"],
            "realtime_ticket_rpc_unavailable",
        )


class ManualSandboxCheckoutTests(unittest.TestCase):
    def test_owner_can_create_sandbox_checkout_without_agent_invocation(self) -> None:
        business_id = UUID("ec1bdf46-3672-443a-b3d6-0d8c1252ddac")
        user_id = UUID("6ae108fb-138b-4ce8-84cf-c42cb80926ac")
        request = SimpleNamespace(state=SimpleNamespace(request_id="request-id"))
        body = AgentCardManualCheckoutRequest.model_validate(
            {
                "items": [
                    {
                        "product_id": "d7356ad3-ba69-46fd-91d1-daebf6ab7142",
                        "quantity": 2,
                    }
                ]
            }
        )
        result = {
            "checkout_url": "https://shop.example/checkout/test-token",
            "public_transaction_id": "txn_example",
            "status": "awaiting_customer",
            "expires_at": "2026-11-11T22:00:00Z",
            "snapshot": {"total_amount_minor": 12500, "currency": "USD"},
        }
        with (
            patch("src.agentcard.routes.get_business_membership", return_value={"role": "owner"}),
            patch("src.agentcard.routes.require_role"),
            patch(
                "src.agentcard.routes.get_supabase_settings",
                return_value=SimpleNamespace(
                    paypal_api_base_url="https://api-m.sandbox.paypal.com"
                ),
            ),
            patch("src.agentcard.routes.execute", side_effect=[None, None]),
            patch(
                "src.agentcard.routes.create_agentcard_transaction",
                return_value=result,
            ) as create_transaction,
        ):
            response = create_agentcard_test_checkout(
                business_id,
                body,
                request,
                SimpleNamespace(id=user_id),
                MagicMock(),
                MagicMock(),
                "sandbox-test-1",
            )

        self.assertEqual(response.data["checkout_url"], result["checkout_url"])
        self.assertEqual(response.data["total_amount_minor"], 12500)
        self.assertEqual(create_transaction.call_args.kwargs["items"], body.items)


if __name__ == "__main__":
    unittest.main()

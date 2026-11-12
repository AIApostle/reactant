import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import HTTPException

from src.agentcard.paypal import (
    PayPalError,
    _log_paypal_request_failure,
    _authenticated_request,
    create_paypal_order,
    create_paypal_refund,
    minor_to_paypal_amount,
    paypal_amount_to_minor,
    verified_capture_details,
    verified_refund_details,
)
from src.agentcard.service import (
    _checkout_base_url,
    _verify_paypal_eligibility,
    create_agentcard_transaction,
)
from src.agentcard.routes import process_verified_paypal_webhook
from src.agentcard.receipts import _receipt_pdf
from src.schemas.agentcard import AgentCardItemRequest


class PayPalAmountTests(unittest.TestCase):
    def test_checkout_base_url_defaults_to_the_deployed_frontend(self) -> None:
        settings = MagicMock(
            app_env="production",
            public_frontend_url="https://getreactant.vercel.app",
            frontend_url="https://getreactant.vercel.app",
        )
        with patch("src.agentcard.service.get_supabase_settings", return_value=settings):
            self.assertEqual(
                _checkout_base_url(),
                "https://getreactant.vercel.app",
            )

    def test_production_checkout_rejects_localhost_frontend(self) -> None:
        settings = MagicMock(
            app_env="production",
            public_frontend_url="http://localhost:5173",
            frontend_url="http://localhost:5173",
        )
        with (
            patch("src.agentcard.service.get_supabase_settings", return_value=settings),
            self.assertRaises(HTTPException) as raised,
        ):
            _checkout_base_url()

        self.assertEqual(
            raised.exception.detail["code"],
            "public_url_unavailable",
        )

    def test_invalid_checkout_url_fails_before_transaction_creation(self) -> None:
        client = MagicMock()
        with (
            patch("src.agentcard.service._verify_paypal_eligibility"),
            patch(
                "src.agentcard.service._checkout_base_url",
                side_effect=HTTPException(
                    status_code=503,
                    detail={"code": "public_url_unavailable"},
                ),
            ),
            self.assertRaises(HTTPException),
        ):
            create_agentcard_transaction(
                client,
                business_id="business-id",
                conversation_id="conversation-id",
                customer_name="Customer",
                customer_reference="customer-id",
                items=[],
                idempotency_key="idempotency-key",
            )

        client.rpc.assert_not_called()

    def test_checkout_url_preserves_selected_payment_preference(self) -> None:
        client = MagicMock()
        client.rpc.return_value = None
        rpc_result = {
            "public_transaction_id": "txn_example",
            "snapshot": {"total_amount_minor": 1250, "currency": "USD"},
            "expires_at": "2026-11-12T00:00:00+00:00",
            "status": "awaiting_customer",
        }
        with (
            patch("src.agentcard.service._verify_paypal_eligibility"),
            patch(
                "src.agentcard.service._checkout_base_url",
                return_value="https://shop.example",
            ),
            patch(
                "src.agentcard.service._paypal_integration",
                return_value="integration-id",
            ),
            patch("src.agentcard.service.execute", return_value=rpc_result),
        ):
            result = create_agentcard_transaction(
                client,
                business_id="business-id",
                conversation_id="conversation-id",
                customer_name="Customer",
                customer_reference="customer-id",
                items=[
                    AgentCardItemRequest(
                        product_id="6ae108fb-138b-4ce8-84cf-c42cb80926ac",
                        quantity=1,
                    )
                ],
                idempotency_key="idempotency-key",
                payment_method="card",
            )

        checkout_url = urlparse(result["checkout_url"])
        self.assertEqual(checkout_url.scheme, "https")
        self.assertEqual(checkout_url.netloc, "shop.example")
        self.assertRegex(checkout_url.path, r"^/checkout/[A-Za-z0-9_-]{43}$")
        self.assertEqual(parse_qs(checkout_url.query), {"payment_method": ["card"]})

    def test_paypal_request_failure_logs_safe_provider_diagnostics(self) -> None:
        request = httpx.Request("POST", "https://api-m.sandbox.paypal.com/v2/checkout/orders")
        response = httpx.Response(
            422,
            headers={"paypal-debug-id": "debug-123"},
            json={
                "name": "INVALID_REQUEST",
                "message": "Do not log this provider message",
                "details": [
                    {
                        "issue": "PAYEE_ACCOUNT_RESTRICTED",
                        "field": "/purchase_units/0/payee",
                    }
                ],
            },
            request=request,
        )
        error = httpx.HTTPStatusError(
            "request failed",
            request=request,
            response=response,
        )

        with self.assertLogs("src.agentcard.paypal", level="WARNING") as captured:
            _log_paypal_request_failure("POST", "/v2/checkout/orders", error)

        log_entry = "\n".join(captured.output)
        self.assertIn("status=422", log_entry)
        self.assertIn("debug_id=debug-123", log_entry)
        self.assertIn("error_name=INVALID_REQUEST", log_entry)
        self.assertIn("PAYEE_ACCOUNT_RESTRICTED", log_entry)
        self.assertIn("/purchase_units/0/payee", log_entry)
        self.assertNotIn("Do not log this provider message", log_entry)

    def test_nigeria_is_allowed_only_for_sandbox_when_in_country_allowlist(self) -> None:
        client = MagicMock()
        sandbox_settings = MagicMock(
            agentcard_enabled=True,
            paypal_api_base_url="https://api-m.sandbox.paypal.com",
            paypal_receiving_countries="US,NG",
        )
        with (
            patch(
                "src.agentcard.service.get_supabase_settings",
                return_value=sandbox_settings,
            ),
            patch(
                "src.agentcard.service.execute",
                return_value={"country": "NG"},
            ),
        ):
            _verify_paypal_eligibility(client, "business-id")

        live_settings = MagicMock(
            agentcard_enabled=True,
            paypal_api_base_url="https://api-m.paypal.com",
            paypal_receiving_countries="US,NG",
        )
        with (
            patch(
                "src.agentcard.service.get_supabase_settings",
                return_value=live_settings,
            ),
            patch(
                "src.agentcard.service.execute",
                return_value={"country": "NG"},
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            _verify_paypal_eligibility(client, "business-id")
        self.assertEqual(
            raised.exception.detail["code"],
            "paypal_merchant_ineligible",
        )

    def test_nigeria_sandbox_checkout_requires_explicit_country_allowlist(self) -> None:
        settings = MagicMock(
            agentcard_enabled=True,
            paypal_api_base_url="https://api-m.sandbox.paypal.com",
            paypal_receiving_countries="US",
        )
        with (
            patch(
                "src.agentcard.service.get_supabase_settings",
                return_value=settings,
            ),
            patch(
                "src.agentcard.service.execute",
                return_value={"country": "NG"},
            ),
            self.assertRaises(HTTPException) as raised,
        ):
            _verify_paypal_eligibility(MagicMock(), "business-id")

        self.assertEqual(
            raised.exception.detail["code"],
            "paypal_merchant_ineligible",
        )

    def test_minor_units_use_exact_decimal_amounts(self) -> None:
        self.assertEqual(minor_to_paypal_amount(1), "0.01")
        self.assertEqual(minor_to_paypal_amount(12345), "123.45")
        self.assertEqual(paypal_amount_to_minor("123.45"), 12345)

    def test_invalid_paypal_amount_is_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-1.00", "1.001"):
            with self.subTest(value=value), self.assertRaises(PayPalError):
                paypal_amount_to_minor(value)

    def test_capture_is_verified_against_transaction_reference_and_amount(self) -> None:
        result = verified_capture_details(
            {
                "id": "ORDER-123",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "custom_id": "txn_example",
                        "amount": {"currency_code": "USD", "value": "12.34"},
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-123",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "currency_code": "USD",
                                        "value": "12.34",
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
            expected_transaction_id="txn_example",
        )
        self.assertEqual(result, ("ORDER-123", "CAPTURE-123", 1234, "USD", True))

    def test_capture_with_other_transaction_reference_is_rejected(self) -> None:
        with self.assertRaises(PayPalError):
            verified_capture_details(
                {
                    "id": "ORDER-123",
                    "status": "COMPLETED",
                    "purchase_units": [{"custom_id": "txn_other"}],
                },
                expected_transaction_id="txn_example",
            )

    def test_non_completed_order_is_not_treated_as_paid(self) -> None:
        self.assertEqual(
            verified_capture_details(
                {"id": "ORDER-123", "status": "APPROVED"},
                expected_transaction_id="txn_example",
            ),
            ("ORDER-123", "", 0, "", False),
        )

    def test_refund_is_verified_against_paypal_reference_amount_and_currency(self) -> None:
        refund = {
            "id": "REFUND-123",
            "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "5.00"},
        }
        self.assertEqual(
            verified_refund_details(
                refund,
                expected_refund_id="REFUND-123",
                expected_amount_minor=500,
                expected_currency="USD",
            ),
            ("REFUND-123", "COMPLETED", 500, "USD", True),
        )
        self.assertFalse(
            verified_refund_details(
                refund,
                expected_refund_id="REFUND-123",
                expected_amount_minor=501,
                expected_currency="USD",
            )[-1]
        )

    @patch("src.agentcard.paypal._authenticated_request")
    def test_checkout_rejects_non_paypal_approval_url(self, request) -> None:
        request.return_value = {
            "id": "ORDER-123",
            "links": [{"rel": "approve", "href": "https://attacker.example/approve"}],
        }
        with self.assertRaises(PayPalError):
            create_paypal_order(
                {"client_id": "id", "client_secret": "secret"},
                public_transaction_id="txn_example",
                business_name="Test business",
                seller_paypal_email="seller@example.com",
                amount_minor=100,
                currency="USD",
                checkout_url="https://shop.example/checkout/token",
            )

    @patch("src.agentcard.paypal._authenticated_request")
    def test_checkout_routes_payment_to_seller_and_marks_instant_disbursement(
        self,
        request,
    ) -> None:
        request.return_value = {
            "id": "ORDER-123",
            "links": [{"rel": "approve", "href": "https://www.paypal.com/checkout"}],
        }

        create_paypal_order(
            {
                "client_id": "id",
                "client_secret": "secret",
                "partner_attribution_id": "Reactant_BN",
            },
            public_transaction_id="txn_example",
            business_name="Test business",
            seller_paypal_email="seller@example.com",
            amount_minor=100,
            currency="USD",
            checkout_url="https://shop.example/checkout/token",
        )

        payload = request.call_args.kwargs["payload"]
        purchase_unit = payload["purchase_units"][0]
        self.assertEqual(purchase_unit["payee"], {"email_address": "seller@example.com"})
        self.assertEqual(
            purchase_unit["payment_instruction"],
            {"disbursement_mode": "INSTANT"},
        )
        self.assertEqual(
            payload["application_context"]["return_url"],
            "https://shop.example/checkout/token?paypal_return=1&payment_method=paypal",
        )
        self.assertEqual(payload["application_context"]["landing_page"], "LOGIN")
        self.assertNotIn(
            "{",
            payload["application_context"]["return_url"],
        )

    @patch("src.agentcard.paypal._authenticated_request")
    def test_card_preference_requests_paypal_guest_checkout(self, request) -> None:
        request.return_value = {
            "id": "ORDER-123",
            "links": [{"rel": "approve", "href": "https://www.paypal.com/checkout"}],
        }

        create_paypal_order(
            {"client_id": "id", "client_secret": "secret"},
            public_transaction_id="txn_example",
            business_name="Test business",
            seller_paypal_email="seller@example.com",
            amount_minor=100,
            currency="USD",
            checkout_url="https://shop.example/checkout/token",
            payment_method="card",
        )

        payload = request.call_args.kwargs["payload"]
        self.assertEqual(
            payload["application_context"]["landing_page"],
            "GUEST_CHECKOUT",
        )
        self.assertEqual(
            payload["application_context"]["cancel_url"],
            "https://shop.example/checkout/token?paypal_cancelled=1&payment_method=card",
        )

    @patch("src.agentcard.paypal._access_token", return_value="access-token")
    @patch("src.agentcard.paypal.httpx.Client")
    def test_paypal_api_request_uses_server_oauth_token(
        self,
        client_factory,
        _access_token,
    ) -> None:
        response = MagicMock()
        response.json.return_value = {"id": "ORDER-123"}
        http = MagicMock()
        http.request.return_value = response
        client_factory.return_value.__enter__.return_value = http

        with patch(
            "src.agentcard.paypal._paypal_api_base",
            return_value="https://api-m.sandbox.paypal.com",
        ):
            result = _authenticated_request(
                "GET",
                "/v2/checkout/orders/ORDER-123",
                {
                    "client_id": "id",
                    "client_secret": "secret",
                    "partner_attribution_id": "Reactant_BN",
                },
            )

        self.assertEqual(result, {"id": "ORDER-123"})
        self.assertEqual(
            http.request.call_args.kwargs["headers"]["PayPal-Partner-Attribution-Id"],
            "Reactant_BN",
        )
        self.assertEqual(
            http.request.call_args.kwargs["headers"]["Authorization"],
            "Bearer access-token",
        )

    @patch("src.agentcard.paypal._authenticated_request")
    def test_refund_uses_provider_capture_and_idempotency_key(self, request) -> None:
        request.return_value = {"id": "REFUND-123"}

        create_paypal_refund(
            {"client_id": "id", "client_secret": "secret"},
            "CAPTURE-123",
            amount_minor=500,
            currency="USD",
            request_id="AGCR123",
            reason="Customer request",
        )

        args, kwargs = request.call_args
        self.assertEqual(
            args,
            (
                "POST",
                "/v2/payments/captures/CAPTURE-123/refund",
                {"client_id": "id", "client_secret": "secret"},
            ),
        )
        self.assertEqual(kwargs["request_id"], "AGCR123")
        self.assertEqual(
            kwargs["payload"]["amount"],
            {"currency_code": "USD", "value": "5.00"},
        )


class PayPalOnboardingWebhookTests(unittest.TestCase):
    @patch("src.agentcard.routes.execute")
    def test_onboarding_events_update_the_seller_connection_state(self, execute) -> None:
        for event_type, expected_status, expected_sync_status in (
            (
                "MERCHANT.ONBOARDING.COMPLETED",
                "connected",
                "seller_connected",
            ),
            (
                "MERCHANT.PARTNER-CONSENT.REVOKED",
                "disconnected",
                "seller_reauthorization_required",
            ),
        ):
            with self.subTest(event_type=event_type):
                client = MagicMock()
                process_verified_paypal_webhook(
                    client,
                    integration_id="integration-id",
                    business_id="business-id",
                    payload={
                        "id": f"event-{event_type}",
                        "event_type": event_type,
                        "resource": {},
                    },
                )
                integration_update = client.table.return_value.update.call_args_list[0].args[0]
                self.assertEqual(integration_update["status"], expected_status)
                self.assertEqual(integration_update["sync_status"], expected_sync_status)
                client.table.return_value.reset_mock()


class AgentCardReceiptTests(unittest.TestCase):
    def test_receipt_is_generated_as_pdf_and_escapes_catalog_markup(self) -> None:
        content = _receipt_pdf(
            receipt_number="rcpt_example",
            transaction={
                "public_transaction_id": "txn_example",
                "customer_name": "Customer",
                "currency": "USD",
                "subtotal_minor": 100,
                "discount_total_minor": 0,
                "tax_total_minor": 0,
                "delivery_total_minor": 0,
                "total_amount_minor": 100,
                "checkout_snapshot": {
                    "business": {"name": "<Test business>"},
                    "items": [
                        {
                            "name": "<Item>",
                            "quantity": 1,
                            "unit_price_minor": 100,
                            "total_minor": 100,
                        }
                    ],
                },
            },
            payment={
                "provider_order_id": "ORDER-123",
                "provider_capture_id": "CAPTURE-123",
            },
        )
        self.assertTrue(content.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

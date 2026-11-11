import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import SecretStr

from src.agentcard.paypal import PayPalError, platform_paypal_credentials
from src.integrations.routes import _validate_provider_credentials
from src.schemas.integrations import IntegrationCreate
from src.supabase.client import SupabaseSettings


class AgentCardPayPalSetupTests(unittest.TestCase):
    def test_existing_bn_code_environment_variable_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_PERISHABLE_KEY": "test-key",
                "PAYPAL_BN_CODE": "sandbox-bn-code",
                "PAYPAL_ONBOARDING_AFTER_PAYMENT_ENABLED": "True",
            },
            clear=True,
        ):
            settings = SupabaseSettings(_env_file=None)

        self.assertEqual(settings.paypal_partner_attribution_id, "sandbox-bn-code")
        self.assertTrue(settings.paypal_onboarding_after_payment_enabled)

    def test_partner_mode_uses_server_credentials_and_seller_email(self) -> None:
        settings = SimpleNamespace(
            paypal_onboarding_after_payment_enabled=True,
            paypal_api_base_url="https://api-m.sandbox.paypal.com",
            paypal_client_id=SecretStr("reactant-sandbox-client"),
            paypal_secret_key=SecretStr("reactant-sandbox-secret"),
            paypal_partner_attribution_id="Reactant_BN",
        )
        body = IntegrationCreate.model_validate(
            {
                "provider": "paypal",
                "credentials": {"seller_paypal_email": "seller@example.com"},
            }
        )

        with patch(
            "src.agentcard.paypal.get_supabase_settings",
            return_value=settings,
        ), patch(
            "src.integrations.routes.platform_paypal_credentials",
            return_value={
                "client_id": "reactant-sandbox-client",
                "client_secret": "reactant-sandbox-secret",
                "partner_attribution_id": "Reactant_BN",
            },
        ):
            self.assertEqual(
                _validate_provider_credentials(body),
                {
                    "mode": "partner_after_payment",
                    "seller_paypal_email": "seller@example.com",
                },
            )
            self.assertEqual(
                platform_paypal_credentials(),
                {
                    "client_id": "reactant-sandbox-client",
                    "client_secret": "reactant-sandbox-secret",
                    "partner_attribution_id": "Reactant_BN",
                },
            )

    def test_partner_configuration_is_required_before_seller_setup(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "paypal",
                "credentials": {"seller_paypal_email": "seller@example.com"},
            }
        )

        with patch(
            "src.integrations.routes.platform_paypal_credentials",
            side_effect=PayPalError("not configured"),
        ):
            with self.assertRaises(HTTPException) as raised:
                _validate_provider_credentials(body)

        self.assertEqual(
            raised.exception.detail["code"],
            "paypal_partner_not_configured",
        )

    def test_business_paypal_app_credentials_are_rejected(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "paypal",
                "credentials": {
                    "seller_paypal_email": "seller@example.com",
                    "consumer_key": "business-client-id",
                    "consumer_secret": "business-app-secret",
                },
            }
        )

        with self.assertRaises(HTTPException) as raised:
            _validate_provider_credentials(body)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            raised.exception.detail["code"],
            "paypal_business_credentials_not_allowed",
        )

    def test_seller_paypal_email_is_required(self) -> None:
        body = IntegrationCreate.model_validate(
            {"provider": "paypal", "credentials": {}}
        )

        with patch(
            "src.integrations.routes.platform_paypal_credentials",
            return_value={"client_id": "id", "client_secret": "secret"},
        ):
            with self.assertRaises(HTTPException) as raised:
                _validate_provider_credentials(body)

        self.assertEqual(raised.exception.detail["code"], "paypal_seller_email_required")

    def test_partner_credentials_require_bn_code_and_explicit_opt_in(self) -> None:
        base_settings = {
            "paypal_api_base_url": "https://api-m.sandbox.paypal.com",
            "paypal_client_id": SecretStr("reactant-client"),
            "paypal_secret_key": SecretStr("reactant-secret"),
            "paypal_partner_attribution_id": "Reactant_BN",
        }
        for overrides in (
            {"paypal_onboarding_after_payment_enabled": False},
            {
                "paypal_onboarding_after_payment_enabled": True,
                "paypal_partner_attribution_id": None,
            },
        ):
            with self.subTest(overrides=overrides):
                settings = SimpleNamespace(**{**base_settings, **overrides})
                with patch(
                    "src.agentcard.paypal.get_supabase_settings",
                    return_value=settings,
                ):
                    with self.assertRaises(PayPalError):
                        platform_paypal_credentials()


if __name__ == "__main__":
    unittest.main()

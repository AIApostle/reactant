import unittest

from fastapi import HTTPException

from src.integrations.routes import _validate_provider_credentials
from src.schemas.integrations import IntegrationCreate


class AgentCardPayPalSetupTests(unittest.TestCase):
    def test_paypal_credentials_can_be_connected_before_webhook_creation(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "paypal",
                "credentials": {
                    "consumer_key": "sandbox-client-id",
                    "consumer_secret": "sandbox-client-secret",
                },
            }
        )

        self.assertEqual(
            _validate_provider_credentials(body),
            {
                "consumer_key": "sandbox-client-id",
                "consumer_secret": "sandbox-client-secret",
            },
        )

    def test_paypal_credentials_keep_an_already_configured_webhook(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "paypal",
                "credentials": {
                    "consumer_key": "sandbox-client-id",
                    "consumer_secret": "sandbox-client-secret",
                    "webhook_id": "WH-123",
                },
            }
        )

        self.assertEqual(_validate_provider_credentials(body)["webhook_id"], "WH-123")

    def test_paypal_client_credentials_are_still_required(self) -> None:
        body = IntegrationCreate.model_validate(
            {"provider": "paypal", "credentials": {"consumer_key": "sandbox-client-id"}}
        )

        with self.assertRaises(HTTPException) as raised:
            _validate_provider_credentials(body)

        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

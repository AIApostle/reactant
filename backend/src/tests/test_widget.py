import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from src.agent.memory import memory_namespace
from src.integrations.routes import _validate_provider_credentials
from src.schemas.integrations import IntegrationCreate
from src.widget import routes


class WidgetSessionTests(unittest.TestCase):
    def test_session_token_round_trip_binds_origin_and_memory_consent(self) -> None:
        business_id = str(uuid4())
        conversation_id = str(uuid4())
        visitor_id = str(uuid4())
        with patch.object(routes, "_signing_key", return_value=b"test-signing-key"):
            token = routes._issue_session_token(
                business_id=business_id,
                conversation_id=conversation_id,
                visitor_id=visitor_id,
                origin="https://shop.example",
                memory_consent=True,
            )
            claims = routes._read_session_token(token)

        self.assertEqual(claims["business_id"], business_id)
        self.assertEqual(claims["conversation_id"], conversation_id)
        self.assertEqual(claims["visitor_id"], visitor_id)
        self.assertEqual(claims["origin"], "https://shop.example")
        self.assertTrue(claims["memory_consent"])

    def test_tampered_session_token_is_rejected(self) -> None:
        with (
            patch.object(routes, "_signing_key", return_value=b"test-signing-key"),
            self.assertRaises(HTTPException) as raised,
        ):
            token = routes._issue_session_token(
                business_id=str(uuid4()),
                conversation_id=str(uuid4()),
                visitor_id=str(uuid4()),
                origin="https://shop.example",
                memory_consent=False,
            )
            encoded, signature = token.split(".", 1)
            changed_first_character = "A" if signature[0] != "A" else "B"
            routes._read_session_token(f"{encoded}.{changed_first_character}{signature[1:]}")

        self.assertEqual(raised.exception.status_code, 401)

    def test_image_query_uses_product_context_without_request_words(self) -> None:
        query = routes._image_query("Can you show me photos of red shoes?", [])
        self.assertEqual(query, "red shoes")

    def test_image_query_uses_the_most_recent_customer_context(self) -> None:
        query = routes._image_query(
            "Can you show me a photo of that one?",
            [
                {"sender_type": "customer", "text": "Blue hat"},
                {"sender_type": "customer", "text": "Red shoes"},
            ],
        )
        self.assertEqual(query, "blue hat")

    def test_image_query_ignores_vague_product_reference_words(self) -> None:
        query = routes._image_query(
            "Can I see a picture of the product you guys have (my message)?",
            [{"sender_type": "customer", "text": "Do you have shoes?"}],
        )
        self.assertEqual(query, "shoes")

    def test_customer_memory_namespaces_are_isolated_by_business_and_customer(self) -> None:
        first_business = str(uuid4())
        second_business = str(uuid4())
        first = memory_namespace(
            first_business,
            audience="customer",
            customer_reference="visitor-1",
        )
        self.assertNotEqual(
            first,
            memory_namespace(
                first_business,
                audience="customer",
                customer_reference="visitor-2",
            ),
        )
        self.assertNotEqual(
            first,
            memory_namespace(
                second_business,
                audience="customer",
                customer_reference="visitor-1",
            ),
        )
        self.assertNotEqual(
            first,
            memory_namespace(
                first_business,
                audience="owner",
            ),
        )

    def test_website_origin_normalizes_default_port_and_case(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "website_chat",
                "credentials": {"allowed_origin": "https://Shop.Example:443/"},
            }
        )
        credentials = _validate_provider_credentials(body)
        self.assertEqual(credentials["allowed_origin"], "https://shop.example")

    def test_website_origin_rejects_malformed_url(self) -> None:
        body = IntegrationCreate.model_validate(
            {
                "provider": "website_chat",
                "credentials": {"allowed_origin": "https://["},
            }
        )
        with self.assertRaises(HTTPException) as raised:
            _validate_provider_credentials(body)
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

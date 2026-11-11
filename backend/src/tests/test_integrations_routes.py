import unittest
from unittest.mock import patch

from fastapi import HTTPException
from postgrest.exceptions import APIError

from src.integrations.routes import (
    BASE_VISIBLE_FIELDS,
    VISIBLE_FIELDS,
    _execute_integration_query,
    _telegram_api,
)


class IntegrationSchemaCompatibilityTests(unittest.TestCase):
    def test_missing_allowed_origin_retries_with_compatible_fields(self) -> None:
        queries = []

        def execute(query):
            queries.append(query)
            if len(queries) == 1:
                try:
                    raise APIError(
                        {
                            "code": "42703",
                            "message": "column integrations.allowed_origin does not exist",
                        }
                    )
                except APIError as error:
                    raise HTTPException(
                        status_code=503,
                        detail={"code": "database_schema_outdated"},
                    ) from error
            return [{"id": "integration-id"}]

        with patch("src.integrations.routes.execute", side_effect=execute):
            result = _execute_integration_query(
                lambda fields, include_origin: (fields, include_origin)
            )

        self.assertEqual(queries, [(VISIBLE_FIELDS, True), (BASE_VISIBLE_FIELDS, False)])
        self.assertEqual(result, [{"id": "integration-id"}])

    def test_unrelated_schema_errors_are_not_retried(self) -> None:
        def execute(_query):
            try:
                raise APIError(
                    {
                        "code": "42703",
                        "message": "column integrations.provider does not exist",
                    }
                )
            except APIError as error:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "database_schema_outdated"},
                ) from error

        with patch("src.integrations.routes.execute", side_effect=execute) as mocked_execute:
            with self.assertRaises(HTTPException):
                _execute_integration_query(
                    lambda fields, include_origin: (fields, include_origin)
                )

        mocked_execute.assert_called_once()


class TelegramApiResponseTests(unittest.TestCase):
    @patch("src.integrations.routes.httpx.post")
    def test_accepts_telegram_set_webhook_boolean_result(self, post) -> None:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"ok": True, "result": True}

        result = _telegram_api("bot-token", "setWebhook", {"url": "https://example.test"})

        self.assertIs(result, True)

    @patch("src.integrations.routes.httpx.post")
    def test_rejects_malformed_get_me_result(self, post) -> None:
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"ok": True, "result": True}

        with self.assertRaises(HTTPException) as raised:
            _telegram_api("bot-token", "getMe", {})

        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(
            raised.exception.detail["code"],
            "telegram_invalid_response",
        )


if __name__ == "__main__":
    unittest.main()

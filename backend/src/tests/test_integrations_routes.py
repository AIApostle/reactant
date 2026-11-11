import unittest
from unittest.mock import patch

from fastapi import HTTPException
from postgrest.exceptions import APIError

from src.integrations.routes import (
    BASE_VISIBLE_FIELDS,
    VISIBLE_FIELDS,
    _execute_integration_query,
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


if __name__ == "__main__":
    unittest.main()

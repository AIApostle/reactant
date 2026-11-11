import unittest

from fastapi import HTTPException
from postgrest.exceptions import APIError

from src.supabase.repository import execute_response


class DatabaseSchemaErrorTests(unittest.TestCase):
    def test_missing_database_column_has_actionable_error(self) -> None:
        class Query:
            def execute(self):
                raise APIError(
                    {
                        "code": "42703",
                        "message": "column integrations.allowed_origin does not exist",
                    }
                )

        with self.assertRaises(HTTPException) as raised:
            execute_response(Query())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["code"], "database_schema_outdated")

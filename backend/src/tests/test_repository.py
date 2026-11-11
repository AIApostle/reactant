import unittest

from fastapi import HTTPException
from postgrest.exceptions import APIError

from src.supabase.repository import execute, execute_response


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

    def test_missing_rpc_is_reported_as_outdated_schema(self) -> None:
        class Query:
            def execute(self):
                raise APIError(
                    {
                        "code": "PGRST202",
                        "message": "Could not find the function public.create_realtime_ticket",
                    }
                )

        with self.assertRaises(HTTPException) as raised:
            execute_response(Query())

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["code"], "database_schema_outdated")
        self.assertIn("schema cache", raised.exception.detail["message"])


class MaybeSingleQueryTests(unittest.TestCase):
    def test_execute_preserves_no_rows_result_from_maybe_single_query(self) -> None:
        class Query:
            def execute(self):
                return None

        self.assertIsNone(execute(Query()))

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
from starlette.requests import Request

from src.agent import customer_worker
from src.webhooks import routes as webhook_routes


class CustomerAgentWorkerTests(unittest.TestCase):
    def test_customer_run_dispatches_website_message_and_completes_lease(self) -> None:
        run = {
            "id": str(uuid4()),
            "business_id": str(uuid4()),
            "source_type": "customer_message",
            "lease_token": str(uuid4()),
        }
        client = MagicMock()
        with (
            patch.object(customer_worker, "_process_website_message") as process,
            patch.object(customer_worker, "execute") as execute,
        ):
            customer_worker._process_customer_run(client, run)

        process.assert_called_once_with(client, run)
        client.rpc.assert_called_once_with(
            "complete_customer_agent_run",
            {
                "target_business_id": run["business_id"],
                "target_run_id": run["id"],
                "requested_lease_token": run["lease_token"],
            },
        )
        execute.assert_called_once()

    def test_customer_run_dispatches_telegram_update(self) -> None:
        run = {
            "id": str(uuid4()),
            "business_id": str(uuid4()),
            "source_type": "telegram_update",
            "lease_token": str(uuid4()),
        }
        client = MagicMock()
        with (
            patch.object(customer_worker, "_process_telegram_run") as process,
            patch.object(customer_worker, "execute"),
        ):
            customer_worker._process_customer_run(client, run)

        process.assert_called_once_with(client, run)

    def test_telegram_queue_payload_is_decrypted_before_processing(self) -> None:
        key = Fernet.generate_key()
        payload = {"update_id": 123, "message": {"text": "hello"}}
        encrypted = Fernet(key).encrypt(json.dumps(payload).encode()).decode()
        run = {"telegram_payload_ciphertext": encrypted}

        with patch.object(
            customer_worker,
            "get_supabase_settings",
            return_value=type(
                "Settings",
                (),
                {"credentials_encryption_key": SecretStr(key.decode())},
            )(),
        ):
            self.assertEqual(customer_worker._telegram_payload(run), payload)

    def test_customer_run_rejects_unknown_source(self) -> None:
        run = {
            "id": str(uuid4()),
            "business_id": str(uuid4()),
            "source_type": "unknown",
        }
        with self.assertRaisesRegex(RuntimeError, "unsupported source"):
            customer_worker._process_customer_run(MagicMock(), run)

    def test_telegram_webhook_persists_encrypted_work_without_running_agent(self) -> None:
        key = Fernet.generate_key()
        channel_id = uuid4()
        business_id = uuid4()
        payload = {
            "update_id": 456,
            "message": {
                "chat": {"id": 789},
                "from": {"id": 789},
                "text": "Hi",
            },
        }

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(payload).encode(),
                "more_body": False,
            }

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": f"/webhooks/telegram/{channel_id}",
                "headers": [
                    (b"x-telegram-bot-api-secret-token", b"secret"),
                ],
                "query_string": b"",
                "server": ("testserver", 80),
                "client": ("testclient", 123),
                "scheme": "http",
            },
            receive,
        )
        request.state.request_id = "request-id"
        client = MagicMock()

        async def invoke() -> None:
            with (
                patch.object(webhook_routes, "get_service_supabase_client", return_value=client),
                patch.object(
                    webhook_routes,
                    "get_supabase_settings",
                    return_value=type(
                        "Settings",
                        (),
                        {"credentials_encryption_key": SecretStr(key.decode())},
                    )(),
                ),
                patch.object(
                    webhook_routes,
                    "_integration_credentials",
                    return_value=(
                        {"bot_token": "bot-token", "webhook_secret": "secret"},
                        business_id,
                    ),
                ),
                patch.object(webhook_routes, "_mark_telegram_connected"),
                patch.object(webhook_routes, "_persist_event", return_value=False),
                patch.object(webhook_routes, "execute") as execute,
                patch.object(webhook_routes, "_process_telegram_update") as process_update,
            ):
                response = await webhook_routes.receive_telegram_webhook(
                    channel_id,
                    request,
                )

            self.assertFalse(response.data.duplicate)
            process_update.assert_not_called()
            client.rpc.assert_called_once()
            rpc_name, rpc_args = client.rpc.call_args.args
            self.assertEqual(rpc_name, "enqueue_telegram_customer_agent_run")
            self.assertEqual(rpc_args["target_business_id"], str(business_id))
            stored_payload = Fernet(key).decrypt(
                rpc_args["requested_payload_ciphertext"].encode()
            )
            self.assertEqual(json.loads(stored_payload), payload)
            execute.assert_called_once()

        asyncio.run(invoke())


if __name__ == "__main__":
    unittest.main()

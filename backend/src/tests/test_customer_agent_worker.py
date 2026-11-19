import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
from starlette.requests import Request

from src.agent import customer_worker
from src.agentcard.receipts import _telegram_receipt_caption
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

    def test_customer_run_dispatches_verified_agentcard_payment(self) -> None:
        run = {
            "id": str(uuid4()),
            "business_id": str(uuid4()),
            "source_type": "agentcard_payment",
            "agentcard_transaction_id": str(uuid4()),
            "lease_token": str(uuid4()),
        }
        client = MagicMock()
        with (
            patch.object(customer_worker, "_process_agentcard_payment") as process,
            patch.object(customer_worker, "execute"),
        ):
            customer_worker._process_customer_run(client, run)

        process.assert_called_once_with(client, run)

    def test_verified_payment_agent_sends_a_personal_telegram_thank_you(self) -> None:
        business_id = str(uuid4())
        conversation_id = str(uuid4())
        transaction_id = str(uuid4())
        channel_id = str(uuid4())
        run = {
            "business_id": business_id,
            "agentcard_transaction_id": transaction_id,
        }
        client = MagicMock()
        transaction = {
            "id": transaction_id,
            "business_id": business_id,
            "conversation_id": conversation_id,
            "customer_name": "Ayo",
            "customer_reference": "12345",
            "public_transaction_id": "txn_01234567890123456789",
            "total_amount_minor": 1200,
            "currency": "USD",
        }
        conversation = {"channel": "telegram", "customer_context": {}}
        business = {"name": "Shop", "country": "US", "currency": "USD"}
        results = [
            transaction,
            conversation,
            None,
            business,
            {"enabled": True},
            [],
            {"id": channel_id},
            None,
            None,
            None,
        ]
        settings = type(
            "Settings",
            (),
            {"strands_agent_enabled": True, "has_model_api_key": True},
        )()

        with (
            patch.object(customer_worker, "execute", side_effect=results),
            patch.object(customer_worker, "get_agent_runtime_settings", return_value=settings),
            patch.object(customer_worker, "agent_is_enabled", return_value=True),
            patch.object(customer_worker, "history_with_customer_images", return_value=[]),
            patch.object(customer_worker, "build_business_agent", return_value=object()),
            patch.object(
                customer_worker,
                "invoke_business_agent",
                return_value="Thanks so much for your order, Ayo! We hope to see you again soon.",
            ) as invoke,
            patch(
                "src.webhooks.routes._integration_credentials",
                return_value=({"bot_token": "bot-token"}, UUID(channel_id)),
            ),
            patch("src.webhooks.routes._telegram_send_message") as send_message,
        ):
            customer_worker._process_agentcard_payment(client, run)

        prompt = invoke.call_args.args[1]
        self.assertIn("payment has been verified as complete", prompt)
        send_message.assert_called_once_with(
            "bot-token",
            "12345",
            "Thanks so much for your order, Ayo! We hope to see you again soon.",
        )

    def test_receipt_caption_includes_the_customer_thank_you(self) -> None:
        caption = _telegram_receipt_caption(
            "RCPT-1",
            {"total_amount_minor": 1200, "currency": "USD", "public_transaction_id": "txn_1"},
            {"provider_capture_id": "capture-1"},
        )

        self.assertIn("Thank you for your purchase", caption)

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

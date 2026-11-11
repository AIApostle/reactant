import hashlib
import unittest
from unittest.mock import patch
from uuid import uuid4

from src.webhooks import routes


class OwnerTelegramPairingTests(unittest.TestCase):
    def test_pairing_code_is_redacted_from_webhook_event_storage(self) -> None:
        token = "pairing-code-with-at-least-twenty-characters"
        payload = {
            "update_id": 1000,
            "message": {"text": f"/pair {token}", "caption": None},
        }

        redacted = routes._redact_telegram_pairing_code(payload)

        self.assertNotIn(token, str(redacted))
        self.assertIn("[REDACTED]", redacted["message"]["text"])
        self.assertEqual(payload["message"]["text"], f"/pair {token}")

    def test_pair_code_is_consumed_only_from_the_private_owner_chat(self) -> None:
        channel_id = uuid4()
        business_id = uuid4()
        token = "pairing-code-with-at-least-twenty-characters"

        class FakeClient:
            def rpc(self, name, arguments):
                return (name, arguments)

        with (
            patch.object(routes, "execute", return_value=str(uuid4())) as execute,
            patch.object(routes, "_send_owner_telegram_notice") as notify,
        ):
            handled = routes._handle_owner_telegram_update(
                FakeClient(),
                channel_id=channel_id,
                business_id=business_id,
                bot_token="bot-token",
                chat={"id": 12345, "type": "private"},
                sender={"id": 12345},
                text=f"/pair {token}",
                update_id="1001",
            )

        self.assertTrue(handled)
        query = execute.call_args.args[0]
        self.assertEqual(query[0], "pair_owner_telegram_chat")
        self.assertEqual(
            query[1]["requested_token_hash"],
            hashlib.sha256(token.encode()).hexdigest(),
        )
        self.assertEqual(query[1]["requested_chat_id"], "12345")
        notify.assert_called_once()

    def test_group_chat_cannot_consume_a_pairing_code(self) -> None:
        with (
            patch.object(routes, "execute") as execute,
            patch.object(routes, "_send_owner_telegram_notice") as notify,
        ):
            handled = routes._handle_owner_telegram_update(
                object(),
                channel_id=uuid4(),
                business_id=uuid4(),
                bot_token="bot-token",
                chat={"id": -10012345, "type": "group"},
                sender={"id": 12345},
                text="/pair pairing-code-with-at-least-twenty-characters",
                update_id="1002",
            )

        self.assertTrue(handled)
        execute.assert_not_called()
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()

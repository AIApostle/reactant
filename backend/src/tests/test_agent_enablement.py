import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from starlette.responses import Response

from src.agent.config import agent_is_enabled
from src.agent import routes as agent_routes
from src.schemas.agent import AgentConfigUpdate
from src.webhooks import routes as webhook_routes
from src.widget import routes as widget_routes


class Query:
    def __getattr__(self, _name: str):
        return lambda *_args, **_kwargs: self


class Client:
    def table(self, _name: str) -> Query:
        return Query()


class AgentEnablementTests(unittest.TestCase):
    def test_agent_enablement_fails_closed_for_missing_or_disabled_config(self) -> None:
        self.assertFalse(agent_is_enabled(None))
        self.assertFalse(agent_is_enabled({}))
        self.assertFalse(agent_is_enabled({"enabled": False}))
        self.assertTrue(agent_is_enabled({"enabled": True}))

    def test_agent_update_keeps_status_in_sync_with_enabled(self) -> None:
        for enabled, expected_status in ((True, "active"), (False, "disabled")):
            with self.subTest(enabled=enabled):
                current = {
                    "enabled": not enabled,
                    "status": "disabled" if enabled else "active",
                    "business_context": "",
                    "tone": "warm_helpful",
                    "handoff_rule": "when_uncertain",
                    "permissions": {},
                    "approval_policy": {},
                    "version": 1,
                }
                updated = {
                    **current,
                    "enabled": enabled,
                    "status": expected_status,
                    "version": 2,
                }
                client = MagicMock()
                request = SimpleNamespace(state=SimpleNamespace(request_id="request-id"))
                with (
                    patch.object(agent_routes, "get_business_membership", return_value={}),
                    patch.object(agent_routes, "require_role"),
                    patch.object(agent_routes, "require_matching_etag"),
                    patch.object(agent_routes, "execute", side_effect=[current, updated]),
                ):
                    agent_routes.update_agent_config(
                        business_id=uuid4(),
                        body=AgentConfigUpdate(enabled=enabled),
                        request=request,
                        response=Response(),
                        user=SimpleNamespace(id=uuid4()),
                        client=client,
                        if_match='"1"',
                    )

                changes = client.table.return_value.update.call_args.args[0]
                self.assertEqual(changes["enabled"], enabled)
                self.assertEqual(changes["status"], expected_status)

    def test_telegram_does_not_reply_when_business_agent_is_disabled(self) -> None:
        client = Client()
        with (
            patch.object(
                webhook_routes,
                "execute",
                side_effect=[
                    [],
                    {"id": "conversation-id"},
                    {"id": "message-id"},
                    {},
                    {"name": "Test Business"},
                    {"enabled": False},
                ],
            ),
            patch.object(webhook_routes, "build_business_agent") as build_agent,
            patch.object(webhook_routes, "_telegram_send_message") as send_message,
        ):
            webhook_routes._process_telegram_update(
                client,
                channel_id=uuid4(),
                business_id=uuid4(),
                credentials={"bot_token": "test-token"},
                payload={
                    "update_id": 123,
                    "message": {
                        "chat": {"id": 456},
                        "from": {"id": 456, "first_name": "Customer"},
                        "text": "Hi",
                    },
                },
            )

        build_agent.assert_not_called()
        send_message.assert_not_called()

    def test_website_chat_does_not_reply_when_business_agent_is_disabled(self) -> None:
        with (
            patch.object(
                widget_routes,
                "execute",
                side_effect=[
                    [],
                    {"name": "Test Business"},
                    {"enabled": False},
                ],
            ),
            patch.object(widget_routes, "build_business_agent") as build_agent,
            patch.object(widget_routes, "_save_widget_agent_message") as save_message,
        ):
            widget_routes._process_widget_message(
                Client(),
                claims={
                    "business_id": "business-id",
                    "conversation_id": "conversation-id",
                    "visitor_id": "visitor-id",
                    "memory_consent": False,
                },
                user_text="Hi",
                message_id="message-id",
                images=[],
            )

        build_agent.assert_not_called()
        save_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()

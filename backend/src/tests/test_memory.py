import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from src.agent.memory import (
    get_memory_config,
    memory_namespace,
    recall_memories,
    remember_fact,
)


class MemoryConfigTests(unittest.TestCase):
    def test_reads_backend_memwal_credentials(self) -> None:
        settings = SimpleNamespace(
            memwal_delegate_key=SecretStr("delegate-key"),
            memwal_account_id="account-id",
            memwal_server_url="https://memory.example",
        )
        with patch("src.agent.memory.get_supabase_settings", return_value=settings):
            config = get_memory_config("business-id")

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.private_key, "delegate-key")
        self.assertEqual(config.account_id, "account-id")
        self.assertEqual(config.server_url, "https://memory.example")

    def test_memory_is_disabled_without_required_backend_credentials(self) -> None:
        settings = SimpleNamespace(
            memwal_delegate_key=None,
            memwal_account_id="account-id",
            memwal_server_url=None,
        )
        with patch("src.agent.memory.get_supabase_settings", return_value=settings):
            self.assertIsNone(get_memory_config("business-id"))

    def test_customer_memory_uses_same_isolated_namespace_for_save_and_recall(self) -> None:
        config = SimpleNamespace(
            private_key="delegate-key",
            account_id="account-id",
            server_url="https://memory.example",
        )
        namespace = memory_namespace(
            "business-id",
            audience="customer",
            customer_reference="telegram-chat-123",
        )
        memory_client = MagicMock()
        memory_client.recall.return_value = SimpleNamespace(
            results=[SimpleNamespace(text="Customer prefers size 9")]
        )
        with patch("src.agent.memory.MemWalSync.create", return_value=memory_client):
            recalled = recall_memories(
                config,
                namespace=namespace,
                query="shoe size",
            )
            remember_fact(
                config,
                namespace=namespace,
                content="Customer prefers size 9",
            )

        self.assertEqual(recalled, ["Customer prefers size 9"])
        memory_client.remember_and_wait.assert_called_once_with(
            "Customer prefers size 9",
            namespace=namespace,
        )
        memory_client.recall.assert_called_once()
        self.assertEqual(
            memory_client.recall.call_args.args[0].namespace,
            namespace,
        )

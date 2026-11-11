import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import SecretStr

from src.agent.memory import get_memory_config


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

import os
import unittest
from unittest.mock import patch

from pydantic import SecretStr

from src.supabase.client import SupabaseSettings, get_supabase_settings


class AgentCardSettingsTests(unittest.TestCase):
    def test_public_frontend_defaults_to_deployed_origin(self) -> None:
        settings = SupabaseSettings(
            _env_file=None,
            supabase_url="https://project.supabase.co",
            supabase_perishable_key=SecretStr("test-key"),
        )

        self.assertEqual(settings.frontend_url, "https://reactant-theta.vercel.app")

    def test_enabled_accepts_lower_and_title_case_booleans_from_environment(self) -> None:
        for value in ("true", "True"):
            with self.subTest(value=value), patch.dict(os.environ, {"AGENTCARD_ENABLED": value}):
                get_supabase_settings.cache_clear()
                try:
                    self.assertIs(get_supabase_settings().agentcard_enabled, True)
                finally:
                    get_supabase_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()

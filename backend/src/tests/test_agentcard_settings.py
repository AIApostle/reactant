import os
import unittest
from unittest.mock import patch

from src.supabase.client import get_supabase_settings


class AgentCardSettingsTests(unittest.TestCase):
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

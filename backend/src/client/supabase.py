from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import Client, create_client


class SupabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str
    supabase_perishable_key: SecretStr


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    settings = SupabaseSettings()
    return create_client(
        settings.supabase_url,
        settings.supabase_perishable_key.get_secret_value(),
    )

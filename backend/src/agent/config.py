from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    strands_agent_enabled: bool = False
    openrouter_api_key: SecretStr | None = None
    openrouter_model_id: str = "openrouter/free"
    openrouter_vision_model_id: str = "google/gemini-2.5-flash"
    strands_worker_poll_seconds: float = Field(default=2, ge=0.5, le=60)


def agent_is_enabled(agent_config: dict[str, object] | None) -> bool:
    return isinstance(agent_config, dict) and agent_config.get("enabled") is True


@lru_cache(maxsize=1)
def get_agent_runtime_settings() -> AgentRuntimeSettings:
    return AgentRuntimeSettings()

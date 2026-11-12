from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    strands_agent_enabled: bool = False
    strands_agent_worker_enabled: bool = True
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model_id: str = "gemini-2.5-flash-lite"
    gemini_vision_model_id: str = "gemini-2.5-flash-lite"
    strands_worker_poll_seconds: float = Field(default=2, ge=0.5, le=60)

    @property
    def model_api_key(self) -> SecretStr | None:
        return self.gemini_api_key

    @property
    def has_model_api_key(self) -> bool:
        return self.gemini_api_key is not None

    @property
    def required_api_key_name(self) -> str:
        return "GEMINI_API_KEY"

    def selected_model_id(self, *, vision: bool = False) -> str:
        return self.gemini_vision_model_id if vision else self.gemini_model_id


def agent_is_enabled(agent_config: dict[str, object] | None) -> bool:
    return isinstance(agent_config, dict) and agent_config.get("enabled") is True


@lru_cache(maxsize=1)
def get_agent_runtime_settings() -> AgentRuntimeSettings:
    return AgentRuntimeSettings()

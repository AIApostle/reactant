from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    strands_agent_enabled: bool = False
    agent_model_provider: Literal["google", "openrouter"] = "google"
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model_id: str = "gemini-3.8-flash"
    gemini_vision_model_id: str = "gemini-3.8-flash"
    openrouter_api_key: SecretStr | None = None
    openrouter_model_id: str = "openrouter/free"
    openrouter_vision_model_id: str = "google/gemini-2.5-flash"
    strands_worker_poll_seconds: float = Field(default=2, ge=0.5, le=60)

    @field_validator("gemini_model_id", "gemini_vision_model_id", mode="before")
    @classmethod
    def replace_retired_gemini_model(cls, value: str) -> str:
        if value in {
            "gemini-2.5-flash",
            "models/gemini-2.5-flash",
        }:
            return "gemini-3.8-flash"
        return value

    @property
    def model_api_key(self) -> SecretStr | None:
        return (
            self.gemini_api_key
            if self.agent_model_provider == "google"
            else self.openrouter_api_key
        )

    @property
    def has_model_api_key(self) -> bool:
        if self.agent_model_provider == "google":
            return self.gemini_api_key is not None
        return self.openrouter_api_key is not None or self.gemini_api_key is not None

    @property
    def required_api_key_name(self) -> str:
        return (
            "GEMINI_API_KEY"
            if self.agent_model_provider == "google"
            else "OPENROUTER_API_KEY"
        )

    def selected_model_id(self, *, vision: bool = False) -> str:
        if self.agent_model_provider == "google":
            return self.gemini_vision_model_id if vision else self.gemini_model_id
        return self.openrouter_vision_model_id if vision else self.openrouter_model_id


def agent_is_enabled(agent_config: dict[str, object] | None) -> bool:
    return isinstance(agent_config, dict) and agent_config.get("enabled") is True


@lru_cache(maxsize=1)
def get_agent_runtime_settings() -> AgentRuntimeSettings:
    return AgentRuntimeSettings()

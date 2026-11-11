from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions


class SupabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str
    supabase_perishable_key: SecretStr = Field(
        validation_alias=AliasChoices(
            "SUPABASE_PERISHABLE_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "SUPABASE_ANON_KEY",
        )
    )
    invitation_delivery_url: str | None = None
    invitation_delivery_token: SecretStr | None = None
    credentials_encryption_key: SecretStr | None = None
    supabase_secret_key: SecretStr | None = None
    internal_service_token: SecretStr | None = None
    allowed_web_origins: str = ""
    paypal_api_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_receiving_countries: str = "US"
    agentcard_enabled: bool = False
    paypal_onboarding_after_payment_enabled: bool = False
    public_api_base_url: str | None = None
    public_frontend_url: str = "http://localhost:5173"
    shopify_client_id: str | None = None
    shopify_client_secret: SecretStr | None = None
    shopify_scopes: str = "read_products,read_inventory,read_orders"
    paypal_client_id: SecretStr | None = None
    paypal_secret_key: SecretStr | None = None
    paypal_partner_attribution_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "PAYPAL_PARTNER_ATTRIBUTION_ID",
            "PAYPAL_BN_CODE",
        ),
    )
    paypal_webhook_ids: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="PAYPAL_WEBHOOK_IDS",
    )
    memwal_delegate_key: SecretStr | None = None
    memwal_account_id: str | None = None
    memwal_server_url: str | None = None


@lru_cache(maxsize=1)
def get_supabase_settings() -> SupabaseSettings:
    return SupabaseSettings()


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    settings = get_supabase_settings()
    return create_client(
        settings.supabase_url,
        settings.supabase_perishable_key.get_secret_value(),
    )


bearer_scheme = HTTPBearer(auto_error=False)


def get_user_supabase_client(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
) -> Client:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthenticated",
                "message": "Authentication is required.",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_supabase_settings()
    client = create_client(
        settings.supabase_url,
        settings.supabase_perishable_key.get_secret_value(),
        SyncClientOptions(headers={"Authorization": f"Bearer {credentials.credentials}"}),
    )
    return client


def get_service_supabase_client() -> Client:
    settings = get_supabase_settings()
    if settings.supabase_secret_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "service_database_unavailable", "message": "The service is not configured."},
        )
    return create_client(
        settings.supabase_url,
        settings.supabase_secret_key.get_secret_value(),
    )

import httpx

from src.supabase.client import get_supabase_settings


def deliver_invitation(
    *,
    email: str,
    role: str,
    business_id: str,
    invitation_token: str,
) -> None:
    settings = get_supabase_settings()
    if not settings.invitation_delivery_url or not settings.invitation_delivery_token:
        raise RuntimeError("Invitation delivery is not configured.")
    if not settings.invitation_delivery_url.startswith("https://"):
        raise RuntimeError("Invitation delivery must use HTTPS.")

    try:
        response = httpx.post(
            settings.invitation_delivery_url,
            headers={
                "Authorization": f"Bearer {settings.invitation_delivery_token.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "role": role,
                "business_id": business_id,
                "invitation_token": invitation_token,
            },
            timeout=10,
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise RuntimeError("Invitation delivery failed.") from error

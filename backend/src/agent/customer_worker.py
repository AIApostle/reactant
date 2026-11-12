import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from supabase import Client

from src.agent.config import get_agent_runtime_settings
from src.agent.customer_images import load_customer_images
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_settings,
)
from src.supabase.repository import execute


logger = logging.getLogger(__name__)
CUSTOMER_RUN_MAX_ATTEMPTS = 3
CUSTOMER_RUN_LEASE_SECONDS = 300
CUSTOMER_RUN_HEARTBEAT_SECONDS = 60


def _claim_next_customer_run(client: Client) -> dict[str, Any] | None:
    rows = execute(client.rpc("claim_customer_agent_run", {}))
    return rows[0] if isinstance(rows, list) and rows else None


def _heartbeat_customer_run(client: Client, run: dict[str, Any]) -> bool:
    return bool(
        execute(
            client.rpc(
                "heartbeat_customer_agent_run",
                {
                    "target_business_id": run["business_id"],
                    "target_run_id": run["id"],
                    "requested_lease_token": run["lease_token"],
                    "lease_seconds": CUSTOMER_RUN_LEASE_SECONDS,
                },
            )
        )
    )


def _telegram_payload(run: dict[str, Any]) -> dict[str, Any]:
    key = get_supabase_settings().credentials_encryption_key
    if key is None:
        raise RuntimeError("Telegram update encryption is not configured.")
    try:
        payload = json.loads(
            Fernet(key.get_secret_value().encode()).decrypt(
                run["telegram_payload_ciphertext"].encode()
            )
        )
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("The queued Telegram update could not be decrypted.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("The queued Telegram update is malformed.")
    return payload


def _process_telegram_run(client: Client, run: dict[str, Any]) -> None:
    from src.webhooks.routes import (
        _integration_credentials,
        _process_telegram_update,
    )

    channel_id = UUID(run["telegram_channel_id"])
    credentials, business_id = _integration_credentials(
        client,
        channel_id,
        "telegram",
    )
    if str(business_id) != run["business_id"]:
        raise RuntimeError("Telegram integration business does not match the queued run.")
    _process_telegram_update(
        client,
        channel_id=channel_id,
        business_id=business_id,
        credentials=credentials,
        payload=_telegram_payload(run),
    )


def _process_website_message(client: Client, run: dict[str, Any]) -> None:
    from src.widget.routes import _process_widget_message

    message = execute(
        client.table("customer_messages")
        .select("id,business_id,conversation_id,sender_id,text,attachments")
        .eq("business_id", run["business_id"])
        .eq("id", run["customer_message_id"])
        .single()
    )
    conversation = execute(
        client.table("conversations")
        .select("channel,customer_context")
        .eq("business_id", run["business_id"])
        .eq("id", message["conversation_id"])
        .single()
    )
    if conversation.get("channel") != "website":
        raise RuntimeError("Queued website message belongs to another channel.")
    context = conversation.get("customer_context")
    context = context if isinstance(context, dict) else {}
    visitor_id = context.get("customer_reference") or message.get("sender_id")
    if not isinstance(visitor_id, str) or not visitor_id:
        raise RuntimeError("Website visitor reference is missing.")
    images = load_customer_images(
        client,
        business_id=run["business_id"],
        conversation_id=message["conversation_id"],
        attachments=message.get("attachments") or [],
    )
    _process_widget_message(
        client,
        claims={
            "business_id": run["business_id"],
            "conversation_id": message["conversation_id"],
            "visitor_id": visitor_id,
            "memory_consent": context.get("memory_opt_in") is True,
        },
        user_text=message["text"],
        message_id=message["id"],
        images=images,
    )


def _process_customer_run(client: Client, run: dict[str, Any]) -> None:
    if run["source_type"] == "telegram_update":
        _process_telegram_run(client, run)
    elif run["source_type"] == "customer_message":
        _process_website_message(client, run)
    else:
        raise RuntimeError("The queued customer agent run has an unsupported source.")
    execute(
        client.rpc(
            "complete_customer_agent_run",
            {
                "target_business_id": run["business_id"],
                "target_run_id": run["id"],
                "requested_lease_token": run["lease_token"],
            },
        )
    )


def _fail_customer_run(client: Client, run: dict[str, Any]) -> None:
    execute(
        client.rpc(
            "fail_customer_agent_run",
            {
                "target_business_id": run["business_id"],
                "target_run_id": run["id"],
                "requested_lease_token": run["lease_token"],
                "max_attempts": CUSTOMER_RUN_MAX_ATTEMPTS,
            },
        )
    )


async def _process_customer_run_with_heartbeat(
    client: Client,
    run: dict[str, Any],
) -> None:
    processing = asyncio.create_task(
        asyncio.to_thread(_process_customer_run, client, run)
    )
    while not processing.done():
        try:
            await asyncio.wait_for(
                asyncio.shield(processing),
                timeout=CUSTOMER_RUN_HEARTBEAT_SECONDS,
            )
        except TimeoutError:
            try:
                renewed = await asyncio.to_thread(
                    _heartbeat_customer_run,
                    client,
                    run,
                )
                if not renewed:
                    logger.warning("Customer agent run lease was lost run_id=%s", run["id"])
            except Exception as error:
                logger.error(
                    "Customer agent run heartbeat failed run_id=%s exception_type=%s",
                    run["id"],
                    type(error).__name__,
                )
    await processing


async def run_customer_agent_worker() -> None:
    runtime_settings = get_agent_runtime_settings()
    if not runtime_settings.strands_agent_enabled:
        return
    if not runtime_settings.has_model_api_key:
        logger.error(
            "Customer agent worker is enabled but GEMINI_API_KEY is not configured."
        )
        return
    if get_supabase_settings().supabase_secret_key is None:
        logger.error(
            "Customer agent worker is enabled but SUPABASE_SECRET_KEY is not configured."
        )
        return
    try:
        client = get_service_supabase_client()
    except HTTPException as error:
        logger.error(
            "Customer agent worker could not start service database client status=%s",
            error.status_code,
        )
        return

    poll_seconds = runtime_settings.strands_worker_poll_seconds
    retry_delay = poll_seconds
    while True:
        try:
            run = await asyncio.to_thread(_claim_next_customer_run, client)
            retry_delay = poll_seconds
            if run is not None:
                try:
                    await _process_customer_run_with_heartbeat(client, run)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.error(
                        "Customer agent run failed run_id=%s exception_type=%s",
                        run.get("id", "unknown"),
                        type(error).__name__,
                    )
                    try:
                        await asyncio.to_thread(_fail_customer_run, client, run)
                    except Exception as failure_error:
                        logger.error(
                            "Customer agent run failure state could not be saved run_id=%s exception_type=%s",
                            run.get("id", "unknown"),
                            type(failure_error).__name__,
                        )
            else:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "Customer agent worker iteration failed exception_type=%s",
                type(error).__name__,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

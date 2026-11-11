import asyncio
import logging
from typing import Any

from fastapi import HTTPException
from supabase import Client

from src.agent.config import get_agent_runtime_settings
from src.agent.runtime import build_business_agent, invoke_business_agent
from src.supabase.client import get_service_supabase_client, get_supabase_settings
from src.supabase.repository import execute


logger = logging.getLogger(__name__)
AGENT_RUN_MAX_ATTEMPTS = 3
AGENT_RUN_LEASE_SECONDS = 300
AGENT_RUN_HEARTBEAT_SECONDS = 60


def _claim_next_run(client: Client) -> dict[str, Any] | None:
    rows = execute(client.rpc("claim_agent_run", {}))
    return rows[0] if isinstance(rows, list) and rows else None


def _heartbeat(client: Client, run: dict[str, Any]) -> bool:
    return bool(
        execute(
            client.rpc(
                "heartbeat_agent_run",
                {
                    "target_business_id": run["business_id"],
                    "target_run_id": run["id"],
                    "requested_lease_token": run["lease_token"],
                    "lease_seconds": AGENT_RUN_LEASE_SECONDS,
                },
            )
        )
    )


def _load_history(client: Client, run: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    input_message = execute(
        client.table("owner_messages")
        .select("id,thread_id,text,created_at")
        .eq("business_id", run["business_id"])
        .eq("id", run["input_message_id"])
        .single()
    )
    rows = execute(
        client.table("owner_messages")
        .select("id,sender_type,text")
        .eq("business_id", run["business_id"])
        .eq("thread_id", input_message["thread_id"])
        .lte("created_at", input_message["created_at"])
        .order("created_at", desc=True)
        .limit(8)
    )
    chronological_rows = list(reversed(rows))
    input_index = next(
        (
            index
            for index, row in enumerate(chronological_rows)
            if row["id"] == input_message["id"]
        ),
        None,
    )
    if input_index is None:
        raise RuntimeError("The queued owner message is missing from its thread.")

    history = [
        {
            "role": "assistant" if row["sender_type"] == "agent" else "user",
            "content": [{"text": row["text"][:1500]}],
        }
        for row in chronological_rows[:input_index]
    ]
    return input_message, history


def _process_run(client: Client, run: dict[str, Any]) -> None:
    try:
        message, history = _load_history(client, run)
        business = execute(
            client.table("businesses")
            .select("name,country,currency,return_policy,delivery_policy")
            .eq("id", run["business_id"])
            .single()
        )
        agent_config = execute(
            client.table("agent_configs")
            .select("business_context,tone,handoff_rule,permissions,approval_policy")
            .eq("business_id", run["business_id"])
            .maybe_single()
        )
        agent = build_business_agent(
            client=client,
            business_id=run["business_id"],
            settings=get_agent_runtime_settings(),
            business=business,
            agent_config=agent_config,
            history=history,
            audience="owner",
            agent_run_id=run["id"],
        )
        response_text = invoke_business_agent(agent, message["text"])
        execute(
            client.rpc(
                "complete_agent_run",
                {
                    "target_business_id": run["business_id"],
                    "target_run_id": run["id"],
                    "requested_lease_token": run["lease_token"],
                    "response_text": response_text,
                },
            )
        )
    except Exception as error:
        logger.error(
            "Agent run failed run_id=%s exception_type=%s",
            run.get("id", "unknown"),
            type(error).__name__,
        )
        try:
            execute(
                client.rpc(
                    "fail_agent_run",
                    {
                        "target_business_id": run["business_id"],
                        "target_run_id": run["id"],
                        "requested_lease_token": run["lease_token"],
                        "max_attempts": AGENT_RUN_MAX_ATTEMPTS,
                    },
                )
            )
        except Exception as failure_error:
            logger.error(
                "Agent run failure state could not be saved run_id=%s exception_type=%s",
                run.get("id", "unknown"),
                type(failure_error).__name__,
            )


async def _process_with_heartbeat(client: Client, run: dict[str, Any]) -> None:
    processing = asyncio.create_task(asyncio.to_thread(_process_run, client, run))
    while not processing.done():
        try:
            await asyncio.wait_for(
                asyncio.shield(processing),
                timeout=AGENT_RUN_HEARTBEAT_SECONDS,
            )
        except TimeoutError:
            try:
                renewed = await asyncio.to_thread(_heartbeat, client, run)
                if not renewed:
                    logger.warning("Agent run lease was lost run_id=%s", run["id"])
            except Exception as error:
                logger.error(
                    "Agent run lease heartbeat failed run_id=%s exception_type=%s",
                    run["id"],
                    type(error).__name__,
                )
    await processing


async def run_agent_worker() -> None:
    runtime_settings = get_agent_runtime_settings()
    if not runtime_settings.strands_agent_enabled:
        return
    if not runtime_settings.has_model_api_key:
        logger.error(
            "Strands worker is enabled but neither GEMINI_API_KEY nor "
            "OPENROUTER_API_KEY is configured."
        )
        return
    if get_supabase_settings().supabase_secret_key is None:
        logger.error(
            "Strands worker is enabled but SUPABASE_SECRET_KEY is not configured."
        )
        return
    try:
        client = get_service_supabase_client()
    except HTTPException as error:
        logger.error(
            "Strands worker could not start service database client status=%s",
            error.status_code,
        )
        return

    poll_seconds = runtime_settings.strands_worker_poll_seconds
    retry_delay = poll_seconds
    while True:
        try:
            run = await asyncio.to_thread(_claim_next_run, client)
            retry_delay = poll_seconds
            if run is not None:
                await _process_with_heartbeat(client, run)
            else:
                await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "Strands worker iteration failed exception_type=%s",
                type(error).__name__,
            )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


def require_agent_runtime() -> None:
    runtime_settings = get_agent_runtime_settings()
    if not runtime_settings.strands_agent_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "agent_runtime_disabled",
                "message": "The agent runtime is not configured.",
            },
        )
    if not runtime_settings.has_model_api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "agent_runtime_unavailable",
                "message": (
                    "The agent runtime requires GEMINI_API_KEY or "
                    "OPENROUTER_API_KEY."
                ),
            },
        )
    if get_supabase_settings().supabase_secret_key is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "agent_runtime_unavailable",
                "message": "The agent runtime is not configured.",
            },
        )

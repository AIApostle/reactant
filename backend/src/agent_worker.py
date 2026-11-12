import asyncio
import logging
import signal

from src.agent.config import get_agent_runtime_settings
from src.agent.customer_worker import run_customer_agent_worker
from src.agent.worker import run_agent_worker
from src.supabase.client import get_supabase_settings


logger = logging.getLogger(__name__)


async def _run_until_stopped() -> None:
    worker_tasks = [
        asyncio.create_task(run_agent_worker(), name="strands-agent-worker"),
        asyncio.create_task(
            run_customer_agent_worker(),
            name="strands-customer-agent-worker",
        ),
    ]

    def stop_workers() -> None:
        for task in worker_tasks:
            task.cancel()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(stop_signal, stop_workers)
    try:
        await asyncio.gather(*worker_tasks)
    except asyncio.CancelledError:
        for task in worker_tasks:
            task.cancel()
        await asyncio.gather(*worker_tasks, return_exceptions=True)
        logger.info("Standalone Strands worker stopped.")


def main() -> None:
    settings = get_agent_runtime_settings()
    if not settings.strands_agent_enabled:
        raise SystemExit("Set STRANDS_AGENT_ENABLED=true for the agent worker service.")
    if not settings.strands_agent_worker_enabled:
        raise SystemExit("Set STRANDS_AGENT_WORKER_ENABLED=true for the agent worker service.")
    if not settings.has_model_api_key:
        raise SystemExit("GEMINI_API_KEY is required for the agent worker service.")
    if get_supabase_settings().supabase_secret_key is None:
        raise SystemExit("SUPABASE_SECRET_KEY is required for the agent worker service.")
    asyncio.run(_run_until_stopped())


if __name__ == "__main__":
    main()

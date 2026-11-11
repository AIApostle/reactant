import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID

from memwal import MemWalError, MemWalSync, RecallParams

from src.supabase.client import get_supabase_settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryConfig:
    private_key: str
    account_id: str
    server_url: str | None


def memory_namespace(
    business_id: str,
    *,
    audience: str,
    customer_reference: str | None = None,
) -> str:
    if audience == "owner":
        return f"reactant-business-{business_id}-owner"
    if not customer_reference:
        raise ValueError("A customer reference is required for customer memory.")
    reference_hash = hashlib.sha256(
        f"{business_id}:{customer_reference}".encode()
    ).hexdigest()[:32]
    return f"reactant-business-{business_id}-customer-{reference_hash}"


def get_memory_config(_business_id: str) -> MemoryConfig | None:
    settings = get_supabase_settings()
    if settings.memwal_delegate_key is None or not settings.memwal_account_id:
        return None
    return MemoryConfig(
        private_key=settings.memwal_delegate_key.get_secret_value(),
        account_id=settings.memwal_account_id,
        server_url=settings.memwal_server_url or None,
    )


def recall_memories(
    config: MemoryConfig,
    *,
    namespace: str,
    query: str,
    limit: int = 5,
) -> list[str]:
    memory: MemWalSync | None = None
    try:
        memory = MemWalSync.create(
            key=config.private_key,
            account_id=config.account_id,
            server_url=config.server_url,
        )
        result = memory.recall(
            RecallParams(query=query[:500], limit=max(1, min(limit, 5)), namespace=namespace)
        )
        return [item.text[:500] for item in result.results if item.text.strip()]
    except (MemWalError, OSError, ValueError) as error:
        logger.warning("MemWal recall failed namespace=%s error_type=%s", namespace, type(error).__name__)
        return []
    finally:
        if memory is not None:
            memory.close(clear_keys=True)


def remember_fact(
    config: MemoryConfig,
    *,
    namespace: str,
    content: str,
) -> None:
    memory: MemWalSync | None = None
    try:
        memory = MemWalSync.create(
            key=config.private_key,
            account_id=config.account_id,
            server_url=config.server_url,
        )
        memory.remember_and_wait(content[:2000], namespace=namespace)
    except (MemWalError, OSError, ValueError) as error:
        logger.warning("MemWal remember failed namespace=%s error_type=%s", namespace, type(error).__name__)
        raise RuntimeError("The memory could not be saved.") from error
    finally:
        if memory is not None:
            memory.close(clear_keys=True)


def customer_memory_reference(business_id: UUID, reference: str) -> str:
    return memory_namespace(
        str(business_id),
        audience="customer",
        customer_reference=reference,
    )

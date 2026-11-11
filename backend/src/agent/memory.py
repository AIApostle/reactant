import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from memwal import MemWalError, MemWalSync, RecallParams

from src.supabase.client import get_service_supabase_client, get_supabase_settings
from src.supabase.repository import execute


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MemoryConfig:
    private_key: str
    account_id: str
    network: str


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


def get_memory_config(business_id: str) -> MemoryConfig | None:
    try:
        client = get_service_supabase_client()
        integration = execute(
            client.table("integrations")
            .select("credentials_ciphertext")
            .eq("business_id", business_id)
            .eq("provider", "memwal")
            .eq("status", "connected")
            .limit(1)
        )
    except HTTPException as error:
        logger.warning(
            "MemWal configuration unavailable business_id=%s code=%s",
            business_id,
            getattr(error.detail, "code", "service_database_unavailable"),
        )
        return None
    if not integration:
        return None

    encrypted = integration[0].get("credentials_ciphertext")
    key = get_supabase_settings().credentials_encryption_key
    if not isinstance(encrypted, str) or key is None:
        logger.error("MemWal credentials cannot be read business_id=%s", business_id)
        return None
    try:
        values: Any = json.loads(
            Fernet(key.get_secret_value().encode()).decrypt(encrypted.encode())
        )
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError):
        logger.error("MemWal credentials could not be decrypted business_id=%s", business_id)
        return None
    if not isinstance(values, dict):
        logger.error("MemWal credentials are malformed business_id=%s", business_id)
        return None
    private_key = values.get("private_key")
    account_id = values.get("account_id")
    network = values.get("network")
    if not all(isinstance(value, str) and value for value in (private_key, account_id, network)):
        logger.error("MemWal credentials are incomplete business_id=%s", business_id)
        return None
    return MemoryConfig(private_key=private_key, account_id=account_id, network=network)


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
            env=config.network,
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
            env=config.network,
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

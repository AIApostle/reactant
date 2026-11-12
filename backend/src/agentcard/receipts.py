import asyncio
import hashlib
import html
import json
import logging
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from supabase import Client

from src.agentcard.paypal import (
    PayPalError,
    capture_paypal_order,
    get_paypal_order,
    paypal_credentials,
    verified_capture_details,
)
from src.supabase.client import (
    get_service_supabase_client,
    get_supabase_settings,
)
from src.supabase.repository import execute


logger = logging.getLogger(__name__)
RECEIPT_POLL_SECONDS = 5


def _money(amount_minor: int, currency: str) -> str:
    return f"{currency} {amount_minor / 100:,.2f}"


def _safe_paragraph(value: object) -> str:
    ascii_value = str(value).encode("ascii", "replace").decode("ascii")
    return html.escape(ascii_value)


def _receipt_pdf(
    *,
    receipt_number: str,
    transaction: dict[str, Any],
    payment: dict[str, Any],
    refunds: list[dict[str, Any]] | None = None,
) -> bytes:
    snapshot = transaction["checkout_snapshot"]
    business = snapshot.get("business", {})
    currency = transaction["currency"]
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Receipt {receipt_number}",
        author="Reactant AgentCard",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph("PAYMENT RECEIPT", styles["Title"]),
        Spacer(1, 7 * mm),
        Paragraph(f"Merchant: {_safe_paragraph(business.get('name', 'Business'))}", styles["Normal"]),
        Paragraph(f"Receipt: {_safe_paragraph(receipt_number)}", styles["Normal"]),
        Paragraph(
            f"Transaction: {_safe_paragraph(transaction['public_transaction_id'])}",
            styles["Normal"],
        ),
        Paragraph(
            f"Date: {_safe_paragraph(transaction.get('paid_at') or datetime.now(timezone.utc).isoformat())}",
            styles["Normal"],
        ),
        Paragraph(f"Customer: {_safe_paragraph(transaction['customer_name'])}", styles["Normal"]),
        Paragraph(f"Payment provider: PayPal", styles["Normal"]),
        Paragraph(
            f"Provider reference: {_safe_paragraph(payment.get('provider_capture_id') or payment.get('provider_order_id'))}",
            styles["Normal"],
        ),
        Spacer(1, 8 * mm),
    ]
    rows = [["Item", "Qty", "Unit price", "Total"]]
    for item in snapshot.get("items", []):
        rows.append(
            [
                _safe_paragraph(item.get("name", "Item")),
                str(item.get("quantity", 0)),
                _money(int(item.get("unit_price_minor", 0)), currency),
                _money(int(item.get("total_minor", 0)), currency),
            ]
        )
    rows.extend(
        [
            ["Subtotal", "", "", _money(transaction["subtotal_minor"], currency)],
            ["Discount", "", "", _money(transaction["discount_total_minor"], currency)],
            ["Tax", "", "", _money(transaction["tax_total_minor"], currency)],
            ["Delivery", "", "", _money(transaction["delivery_total_minor"], currency)],
            ["Total paid", "", "", _money(transaction["total_amount_minor"], currency)],
        ]
    )
    completed_refunds = refunds or []
    refunded_amount = sum(int(refund["amount_minor"]) for refund in completed_refunds)
    if completed_refunds:
        rows.extend(
            [
                [
                    f"Refund {_safe_paragraph(refund.get('provider_refund_id') or refund['id'])}",
                    "",
                    "",
                    f"-{_money(int(refund['amount_minor']), currency)}",
                ]
                for refund in completed_refunds
            ]
        )
        rows.append(
            [
                "Net after refunds",
                "",
                "",
                _money(transaction["total_amount_minor"] - refunded_amount, currency),
            ]
        )
    table = Table(rows, colWidths=[78 * mm, 18 * mm, 37 * mm, 37 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2ec")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#173c27")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dce4de")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f4f7f4")),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 10 * mm),
            Paragraph(
                "Original payment verified by PayPal. Completed refunds, if any, are listed above.",
                styles["Normal"],
            ),
        ]
    )
    document.build(story)
    return output.getvalue()


def _claim_receipt(client: Client) -> dict[str, Any] | None:
    rows = execute(client.rpc("claim_agentcard_receipt", {}))
    return rows[0] if isinstance(rows, list) and rows else None


def _reconcile_oldest_payment(client: Client) -> bool:
    stale_before = datetime.fromtimestamp(time.time() - 60, timezone.utc).isoformat()
    rows = execute(
        client.table("agentcard_transactions")
        .select(
            "id,business_id,public_transaction_id,provider_integration_id,total_amount_minor,"
            "currency,status"
        )
        .in_("status", ["payment_processing", "payment_pending", "reconciliation"])
        .lt("updated_at", stale_before)
        .order("updated_at")
        .limit(1)
    )
    if not rows:
        return False
    transaction = rows[0]
    payments = execute(
        client.table("agentcard_payments")
        .select("provider_order_id")
        .eq("business_id", transaction["business_id"])
        .eq("transaction_id", transaction["id"])
        .in_("status", ["created", "processing", "pending", "reconciliation"])
        .order("created_at", desc=True)
        .limit(1)
    )
    if not payments:
        return False
    provider_order_id = payments[0]["provider_order_id"]
    try:
        credentials = paypal_credentials(
            client,
            transaction["business_id"],
            transaction["provider_integration_id"],
        )
        provider_order = get_paypal_order(credentials, provider_order_id)
        if provider_order.get("status") == "APPROVED":
            capture_paypal_order(
                credentials,
                provider_order_id,
                request_id=f"CAP{transaction['public_transaction_id'].removeprefix('txn_')[:32]}",
            )
            provider_order = get_paypal_order(credentials, provider_order_id)
        order_id, capture_id, amount_minor, currency, verified = verified_capture_details(
            provider_order,
            expected_transaction_id=transaction["public_transaction_id"],
        )
        execute(
            client.rpc(
                "record_agentcard_payment_result",
                {
                    "target_provider_order_id": order_id,
                    "target_provider_capture_id": capture_id or None,
                    "target_provider_status": (
                        "COMPLETED"
                        if verified
                        else str(provider_order.get("status", "PENDING"))
                    ),
                    "target_amount_minor": amount_minor,
                    "target_currency": currency or transaction["currency"],
                    "provider_result_verified": verified,
                },
            )
        )
    except (HTTPException, PayPalError, RuntimeError) as error:
        execute(
            client.table("agentcard_transactions")
            .update({"updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("business_id", transaction["business_id"])
            .eq("id", transaction["id"])
        )
        logger.warning(
            "AgentCard payment reconciliation deferred transaction_id=%s exception_type=%s",
            transaction["id"],
            type(error).__name__,
        )
    return True


def _reconcile_oldest_refund(client: Client) -> bool:
    stale_before = datetime.fromtimestamp(time.time() - 60, timezone.utc).isoformat()
    rows = execute(
        client.table("agentcard_refunds")
        .select(
            "id,business_id,transaction_id,provider_refund_id,amount_minor,currency"
        )
        .in_("status", ["pending", "reconciliation"])
        .not_.is_("provider_refund_id", "null")
        .lt("updated_at", stale_before)
        .order("updated_at")
        .limit(1)
    )
    if not rows:
        return False
    refund = rows[0]
    transaction = execute(
        client.table("agentcard_transactions")
        .select("provider_integration_id")
        .eq("business_id", refund["business_id"])
        .eq("id", refund["transaction_id"])
        .single()
    )
    try:
        credentials = paypal_credentials(
            client,
            refund["business_id"],
            transaction["provider_integration_id"],
        )
        provider_refund = get_paypal_refund(credentials, refund["provider_refund_id"])
        refund_id, provider_status, _, _, verified = verified_refund_details(
            provider_refund,
            expected_refund_id=refund["provider_refund_id"],
            expected_amount_minor=refund["amount_minor"],
            expected_currency=refund["currency"],
        )
        execute(
            client.rpc(
                "record_agentcard_refund_result",
                {
                    "target_refund_id": refund["id"],
                    "target_provider_refund_id": refund_id,
                    "target_provider_status": provider_status,
                    "provider_result_verified": verified,
                },
            )
        )
    except (HTTPException, PayPalError, RuntimeError) as error:
        execute(
            client.table("agentcard_refunds")
            .update({"updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("business_id", refund["business_id"])
            .eq("id", refund["id"])
        )
        logger.warning(
            "AgentCard refund reconciliation deferred refund_id=%s exception_type=%s",
            refund["id"],
            type(error).__name__,
        )
    return True


def _receipt_context(
    client: Client,
    receipt: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    transaction = execute(
        client.table("agentcard_transactions")
        .select(
            "id,business_id,order_id,conversation_id,public_transaction_id,customer_name,"
            "customer_reference,currency,subtotal_minor,discount_total_minor,tax_total_minor,"
            "delivery_total_minor,total_amount_minor,status,checkout_snapshot,paid_at"
        )
        .eq("business_id", receipt["business_id"])
        .eq("id", receipt["transaction_id"])
        .in_(
            "status",
            [
                "paid",
                "reconciliation",
                "receipt_issued",
                "receipt_delivered",
                "partially_refunded",
                "refunded",
            ],
        )
        .single()
    )
    payment = execute(
        client.table("agentcard_payments")
        .select("provider_order_id,provider_capture_id,amount_minor,currency,status")
        .eq("business_id", receipt["business_id"])
        .eq("transaction_id", receipt["transaction_id"])
        .eq("status", "completed")
        .single()
    )
    refunds = execute(
        client.table("agentcard_refunds")
        .select("id,provider_refund_id,amount_minor,currency,completed_at")
        .eq("business_id", receipt["business_id"])
        .eq("transaction_id", receipt["transaction_id"])
        .eq("status", "completed")
        .order("completed_at")
    )
    return transaction, payment, refunds


def _telegram_credentials(client: Client, business_id: str) -> dict[str, str] | None:
    integration = execute(
        client.table("integrations")
        .select("credentials_ciphertext")
        .eq("business_id", business_id)
        .eq("provider", "telegram")
        .eq("status", "connected")
        .maybe_single()
    )
    if not integration:
        return None
    settings = get_supabase_settings()
    if settings.credentials_encryption_key is None:
        raise RuntimeError("Credential decryption is not configured.")
    try:
        credentials = json.loads(
            Fernet(settings.credentials_encryption_key.get_secret_value().encode()).decrypt(
                integration["credentials_ciphertext"].encode()
            )
        )
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Telegram integration credentials could not be read.") from error
    if not isinstance(credentials, dict) or not isinstance(credentials.get("bot_token"), str):
        raise RuntimeError("Telegram integration credentials are incomplete.")
    return {"bot_token": credentials["bot_token"]}


def _send_telegram_receipt(
    bot_token: str,
    chat_id: str,
    receipt_number: str,
    transaction: dict[str, Any],
    payment: dict[str, Any],
    pdf: bytes,
) -> str:
    caption = _telegram_receipt_caption(
        receipt_number,
        transaction,
        payment,
    )
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": caption,
            },
            files={"document": ("receipt.pdf", pdf, "application/pdf")},
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise RuntimeError("Telegram receipt delivery failed.") from error
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Telegram receipt delivery failed.")
    message = result.get("result")
    message_id = message.get("message_id") if isinstance(message, dict) else None
    return str(message_id) if message_id is not None else ""


def _update_receipt(
    client: Client,
    receipt: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    result = execute(
        client.table("agentcard_receipts")
        .update(changes)
        .eq("id", receipt["id"])
        .eq("business_id", receipt["business_id"])
        .eq("lease_token", receipt["lease_token"])
        .select("id")
        .maybe_single()
    )
    if not result:
        raise RuntimeError("The receipt processing lease was lost.")


def _telegram_receipt_caption(
    receipt_number: str,
    transaction: dict[str, Any],
    payment: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Payment confirmed by PayPal.",
            f"Receipt: {receipt_number}",
            f"Amount paid: {_money(int(transaction['total_amount_minor']), transaction['currency'])}",
            f"Transaction reference: {transaction['public_transaction_id']}",
            f"PayPal capture reference: {payment.get('provider_capture_id') or 'Unavailable'}",
        ]
    )


def _process_receipt(client: Client, receipt: dict[str, Any]) -> None:
    try:
        transaction, payment, refunds = _receipt_context(client, receipt)
        if receipt.get("storage_path"):
            pdf = client.storage.from_("agentcard-receipts").download(receipt["storage_path"])
        else:
            pdf = _receipt_pdf(
                receipt_number=receipt["receipt_number"],
                transaction=transaction,
                payment=payment,
                refunds=refunds,
            )
            path = f"{receipt['business_id']}/{transaction['id']}.pdf"
            client.storage.from_("agentcard-receipts").upload(
                path,
                pdf,
                {"content-type": "application/pdf", "upsert": "true"},
            )
            _update_receipt(
                client,
                receipt,
                {
                    "storage_path": path,
                    "file_hash": hashlib.sha256(pdf).hexdigest(),
                    "status": "generated",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "last_error": None,
                },
            )
            receipt["storage_path"] = path
            receipt["status"] = "generated"
        execute(
            client.table("agentcard_transactions")
            .update({"status": "receipt_issued", "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("business_id", transaction["business_id"])
            .eq("id", transaction["id"])
            .eq("status", "paid")
        )
        conversation = execute(
            client.table("conversations")
            .select("channel")
            .eq("business_id", transaction["business_id"])
            .eq("id", transaction["conversation_id"])
            .single()
        )
        if conversation["channel"] != "telegram" or not transaction.get("customer_reference"):
            _update_receipt(
                client,
                receipt,
                {
                    "status": "generated",
                    "last_error": "channel_document_delivery_unavailable",
                    "lease_expires_at": datetime.now(timezone.utc).timestamp() + 86400,
                },
            )
            return
        credentials = _telegram_credentials(client, transaction["business_id"])
        if credentials is None:
            _update_receipt(
                client,
                receipt,
                {
                    "status": "generated",
                    "last_error": "telegram_integration_unavailable",
                    "lease_expires_at": datetime.now(timezone.utc).timestamp() + 3600,
                },
            )
            return
        message_id = _send_telegram_receipt(
            credentials["bot_token"],
            transaction["customer_reference"],
            receipt["receipt_number"],
            transaction,
            payment,
            pdf,
        )
        now = datetime.now(timezone.utc).isoformat()
        _update_receipt(
            client,
            receipt,
            {
                "status": "delivered",
                "delivery_channel": "telegram",
                "delivery_reference": message_id or None,
                "delivered_at": now,
                "last_error": None,
                "lease_token": None,
                "lease_expires_at": None,
            },
        )
        execute(
            client.table("agentcard_transactions")
            .update({"status": "receipt_delivered", "updated_at": now})
            .eq("business_id", transaction["business_id"])
            .eq("id", transaction["id"])
            .eq("status", "receipt_issued")
        )
    except Exception as error:
        attempts = int(receipt.get("attempts", 1))
        retry_delay = min(60 * (2 ** min(attempts, 8)), 6 * 60 * 60)
        try:
            _update_receipt(
                client,
                receipt,
                {
                    "status": "failed" if not receipt.get("storage_path") else "generated",
                    "last_error": type(error).__name__,
                    "available_at": datetime.fromtimestamp(
                        time.time() + retry_delay, timezone.utc
                    ).isoformat(),
                    "lease_token": None,
                    "lease_expires_at": None,
                },
            )
        except Exception as update_error:
            logger.error(
                "AgentCard receipt retry state could not be saved receipt_id=%s exception_type=%s",
                receipt.get("id", "unknown"),
                type(update_error).__name__,
            )
        logger.error(
            "AgentCard receipt processing failed receipt_id=%s exception_type=%s",
            receipt.get("id", "unknown"),
            type(error).__name__,
        )


async def run_agentcard_worker() -> None:
    try:
        client = get_service_supabase_client()
    except HTTPException as error:
        logger.error(
            "AgentCard worker could not start service database client status=%s",
            error.status_code,
        )
        return
    while True:
        try:
            await asyncio.to_thread(execute, client.rpc("expire_agentcard_transactions", {}))
            receipt = await asyncio.to_thread(_claim_receipt, client)
            if receipt is not None:
                await asyncio.to_thread(_process_receipt, client, receipt)
            reconciled = await asyncio.to_thread(_reconcile_oldest_payment, client)
            reconciled_refund = await asyncio.to_thread(_reconcile_oldest_refund, client)
            if receipt is None and not reconciled and not reconciled_refund:
                await asyncio.sleep(RECEIPT_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "AgentCard worker iteration failed exception_type=%s",
                type(error).__name__,
            )
            await asyncio.sleep(RECEIPT_POLL_SECONDS)

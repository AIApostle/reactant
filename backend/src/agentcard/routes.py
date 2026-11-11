from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from supabase import Client

from src.agentcard.paypal import (
    capture_paypal_order,
    create_paypal_order,
    create_paypal_refund,
    get_paypal_order,
    get_paypal_refund,
    paypal_amount_to_minor,
    paypal_credentials,
    verified_capture_details,
    verified_refund_details,
)
from src.agentcard.paypal import PayPalError
from src.agentcard.service import (
    _checkout_base_url,
    _checkout_session,
    _record,
    checkout_hash,
    checkout_status,
    checkout_token_hash,
    checkout_view,
    transaction_by_provider_order,
)
from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.agentcard import (
    AgentCardCaptureRequest,
    AgentCardCheckoutResponse,
    AgentCardCheckoutStatus,
    AgentCardConsentRequest,
    AgentCardPaymentRequest,
    AgentCardPaymentResponse,
    AgentCardRefundRequest,
)
from src.schemas.common import ResourceEnvelope
from src.supabase.client import get_service_supabase_client, get_user_supabase_client
from src.supabase.repository import execute, get_business_membership, require_role


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
ServiceDatabase = Annotated[Client, Depends(get_service_supabase_client)]


def _transaction_by_checkout(
    client: Client,
    token: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    session, transaction = _checkout_session(client, token)
    if transaction["status"] in {"cancelled", "expired"}:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "checkout_unavailable",
                "message": "This checkout is no longer available.",
            },
        )
    return session, transaction


@router.get(
    "/agentcard/checkout/{token}",
    response_model=ResourceEnvelope[AgentCardCheckoutResponse],
)
def get_agentcard_checkout(
    token: str,
    request: Request,
    client: ServiceDatabase,
) -> ResourceEnvelope[AgentCardCheckoutResponse]:
    session, transaction = _transaction_by_checkout(client, token)
    return ResourceEnvelope(
        data=AgentCardCheckoutResponse(**checkout_view(client, session, transaction)),
        request_id=request.state.request_id,
    )


@router.get(
    "/agentcard/checkout/{token}/status",
    response_model=ResourceEnvelope[AgentCardCheckoutStatus],
)
def get_agentcard_checkout_status(
    token: str,
    request: Request,
    client: ServiceDatabase,
) -> ResourceEnvelope[AgentCardCheckoutStatus]:
    session, transaction = _transaction_by_checkout(client, token)
    return ResourceEnvelope(
        data=AgentCardCheckoutStatus(**checkout_status(client, session, transaction)),
        request_id=request.state.request_id,
    )


@router.post(
    "/agentcard/checkout/{token}/authorize",
    response_model=ResourceEnvelope[dict[str, str]],
)
def authorize_agentcard_checkout(
    token: str,
    body: AgentCardConsentRequest,
    request: Request,
    client: ServiceDatabase,
) -> ResourceEnvelope[dict[str, str]]:
    session, transaction = _transaction_by_checkout(client, token)
    result = execute(
        client.rpc(
            "authorize_agentcard_checkout",
            {
                "requested_token_hash": checkout_token_hash(token),
                "requested_checkout_hash": checkout_hash(transaction["checkout_snapshot"]),
            },
        )
    )
    result = _record(result)
    return ResourceEnvelope(
        data={
            "authorization_id": str(result["authorization_id"]),
            "status": str(result["status"]),
        },
        request_id=request.state.request_id,
    )


@router.post(
    "/agentcard/checkout/{token}/payment",
    response_model=ResourceEnvelope[AgentCardPaymentResponse],
)
def create_agentcard_payment(
    token: str,
    body: AgentCardPaymentRequest,
    request: Request,
    client: ServiceDatabase,
) -> ResourceEnvelope[AgentCardPaymentResponse]:
    session, transaction = _transaction_by_checkout(client, token)
    if transaction["status"] == "payment_processing":
        payment = execute(
            client.table("agentcard_payments")
            .select("approval_url")
            .eq("business_id", transaction["business_id"])
            .eq("transaction_id", transaction["id"])
            .order("created_at", desc=True)
            .limit(1)
        )
        if payment and payment[0].get("approval_url"):
            return ResourceEnvelope(
                data=AgentCardPaymentResponse(
                    status="payment_processing",
                    approval_url=payment[0]["approval_url"],
                ),
                request_id=request.state.request_id,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "payment_reconciliation_required",
                "message": "This payment attempt is still being checked. Do not retry payment yet.",
            },
        )
    if transaction["status"] != "awaiting_payment":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "checkout_not_ready",
                "message": "Review and authorize this checkout before paying.",
            },
        )
    credentials = paypal_credentials(
        client,
        transaction["business_id"],
        transaction["provider_integration_id"],
    )
    checkout_url = f"{_checkout_base_url()}/checkout/{token}"
    snapshot = transaction["checkout_snapshot"]
    try:
        provider_order_id, approval_url = create_paypal_order(
            credentials,
            public_transaction_id=transaction["public_transaction_id"],
            business_name=snapshot["business"]["name"],
            amount_minor=transaction["total_amount_minor"],
            currency=transaction["currency"],
            checkout_url=checkout_url,
        )
    except PayPalError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "paypal_checkout_unavailable",
                "message": "PayPal could not start this payment. No payment confirmation was received.",
            },
        ) from error
    try:
        execute(
            client.rpc(
                "start_agentcard_payment_attempt",
                {
                    "target_transaction_id": transaction["id"],
                    "target_provider_order_id": provider_order_id,
                    "target_approval_url": approval_url,
                    "target_amount_minor": transaction["total_amount_minor"],
                    "target_currency": transaction["currency"],
                },
            )
        )
    except HTTPException as error:
        existing = execute(
            client.table("agentcard_payments")
            .select("approval_url,status")
            .eq("business_id", transaction["business_id"])
            .eq("provider_order_id", provider_order_id)
            .maybe_single()
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "payment_reconciliation_required",
                    "message": "PayPal created an attempt but Reactant could not confirm it. Do not pay again.",
                },
            ) from error
        approval_url = existing["approval_url"]
    return ResourceEnvelope(
        data=AgentCardPaymentResponse(
            status="payment_processing",
            approval_url=approval_url,
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/agentcard/checkout/{token}/capture",
    response_model=ResourceEnvelope[AgentCardPaymentResponse],
)
def capture_agentcard_payment(
    token: str,
    body: AgentCardCaptureRequest,
    request: Request,
    client: ServiceDatabase,
) -> ResourceEnvelope[AgentCardPaymentResponse]:
    session, transaction = _transaction_by_checkout(client, token)
    payment = execute(
        client.table("agentcard_payments")
        .select("provider_order_id,status")
        .eq("business_id", transaction["business_id"])
        .eq("transaction_id", transaction["id"])
        .eq("provider_order_id", body.provider_order_id)
        .maybe_single()
    )
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "payment_attempt_not_found",
                "message": "The PayPal order does not belong to this checkout.",
            },
        )
    if transaction["status"] == "paid":
        return ResourceEnvelope(
            data=AgentCardPaymentResponse(status="paid"),
            request_id=request.state.request_id,
        )
    credentials = paypal_credentials(
        client,
        transaction["business_id"],
        transaction["provider_integration_id"],
    )
    try:
        current_order = get_paypal_order(credentials, body.provider_order_id)
        if current_order.get("status") == "APPROVED":
            capture_paypal_order(
                credentials,
                body.provider_order_id,
                request_id=f"CAP{transaction['public_transaction_id'].removeprefix('txn_')[:32]}",
            )
            current_order = get_paypal_order(credentials, body.provider_order_id)
        provider_order_id, capture_id, amount_minor, currency, verified = verified_capture_details(
            current_order,
            expected_transaction_id=transaction["public_transaction_id"],
        )
    except PayPalError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "paypal_verification_unavailable",
                "message": "PayPal has not confirmed the payment yet. Do not pay again.",
            },
        ) from error
    capture_status = "COMPLETED" if verified else str(current_order.get("status", "PENDING"))
    result = _record(
        execute(
            client.rpc(
                "record_agentcard_payment_result",
                {
                    "target_provider_order_id": provider_order_id,
                    "target_provider_capture_id": capture_id or None,
                    "target_provider_status": capture_status,
                    "target_amount_minor": amount_minor,
                    "target_currency": currency or transaction["currency"],
                    "provider_result_verified": verified,
                },
            )
        )
    )
    return ResourceEnvelope(
        data=AgentCardPaymentResponse(status=result["status"]),
        request_id=request.state.request_id,
    )


@router.get(
    "/businesses/{business_id}/agentcard/transactions/{transaction_id}",
    response_model=ResourceEnvelope[dict[str, Any]],
)
def get_business_agentcard_transaction(
    business_id: UUID,
    transaction_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, Any]]:
    get_business_membership(client, business_id, user.id)
    transaction = execute(
        client.table("agentcard_transactions")
        .select(
            "id,public_transaction_id,order_id,conversation_id,customer_name,provider,currency,"
            "subtotal_minor,discount_total_minor,tax_total_minor,delivery_total_minor,"
            "total_amount_minor,status,expires_at,paid_at,cancelled_at,failure_reason,created_at,updated_at"
        )
        .eq("business_id", str(business_id))
        .eq("id", str(transaction_id))
        .maybe_single()
    )
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested transaction was not found."},
        )
    transaction["refunds"] = execute(
        client.table("agentcard_refunds")
        .select(
            "id,provider_refund_id,amount_minor,currency,reason,status,created_at,completed_at"
        )
        .eq("business_id", str(business_id))
        .eq("transaction_id", str(transaction_id))
        .order("created_at")
    )
    return ResourceEnvelope(data=transaction, request_id=request.state.request_id)


@router.post(
    "/businesses/{business_id}/agentcard/transactions/{transaction_id}/cancel",
    response_model=ResourceEnvelope[dict[str, str]],
)
def cancel_business_agentcard_transaction(
    business_id: UUID,
    transaction_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[dict[str, str]]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    cancelled = execute(
        client.rpc(
            "cancel_agentcard_transaction",
            {
                "target_business_id": str(business_id),
                "target_transaction_id": str(transaction_id),
                "cancellation_source": "merchant",
            },
        )
    )
    if not cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "transaction_not_cancellable",
                "message": "Only unpaid transactions can be cancelled.",
            },
        )
    return ResourceEnvelope(
        data={"status": "cancelled"},
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/agentcard/transactions/{transaction_id}/refunds",
    response_model=ResourceEnvelope[dict[str, Any]],
)
def refund_business_agentcard_transaction(
    business_id: UUID,
    transaction_id: UUID,
    body: AgentCardRefundRequest,
    request: Request,
    user: User,
    client: Database,
    service_client: ServiceDatabase,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ResourceEnvelope[dict[str, Any]]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin"})
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "idempotency_key_required",
                "message": "A valid Idempotency-Key header is required.",
            },
        )
    transaction = execute(
        service_client.table("agentcard_transactions")
        .select(
            "id,business_id,provider_integration_id,public_transaction_id,status,"
            "total_amount_minor,currency"
        )
        .eq("business_id", str(business_id))
        .eq("id", str(transaction_id))
        .maybe_single()
    )
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested transaction was not found."},
        )
    result = _record(
        execute(
            service_client.rpc(
                "start_agentcard_refund",
                {
                    "target_business_id": str(business_id),
                    "target_transaction_id": str(transaction_id),
                    "target_idempotency_key": idempotency_key.strip(),
                    "target_amount_minor": body.amount_minor,
                    "target_reason": body.reason,
                },
            )
        )
    )
    if result["status"] == "completed":
        return ResourceEnvelope(
            data={
                "refund_id": str(result["refund_id"]),
                "provider_refund_id": result.get("provider_refund_id"),
                "amount_minor": result["amount_minor"],
                "status": "refunded",
            },
            request_id=request.state.request_id,
        )
    payment = execute(
        service_client.table("agentcard_payments")
        .select("provider_capture_id")
        .eq("business_id", str(business_id))
        .eq("transaction_id", str(transaction_id))
        .in_("status", ["completed", "refunded"])
        .order("captured_at", desc=True)
        .limit(1)
    )
    if not payment or not payment[0].get("provider_capture_id"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "refund_reconciliation_required",
                "message": "The captured PayPal payment could not be located. Do not retry with a new idempotency key.",
            },
        )
    credentials = paypal_credentials(
        service_client,
        str(business_id),
        transaction["provider_integration_id"],
    )
    provider_refund_id = result.get("provider_refund_id")
    try:
        if not provider_refund_id:
            created_refund = create_paypal_refund(
                credentials,
                payment[0]["provider_capture_id"],
                amount_minor=body.amount_minor,
                currency=transaction["currency"],
                request_id=f"AGCR{str(result['refund_id']).replace('-', '')[:32]}",
                reason=body.reason,
            )
            provider_refund_id = created_refund.get("id")
            if not isinstance(provider_refund_id, str) or not provider_refund_id:
                raise PayPalError("PayPal did not return a refund reference.")
        provider_refund = get_paypal_refund(credentials, provider_refund_id)
        refund_id, provider_status, amount_minor, currency, verified = verified_refund_details(
            provider_refund,
            expected_refund_id=provider_refund_id,
            expected_amount_minor=body.amount_minor,
            expected_currency=transaction["currency"],
        )
    except PayPalError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "paypal_refund_unavailable",
                "message": "PayPal has not confirmed the refund. Retry with the same idempotency key.",
            },
        ) from error
    result = _record(
        execute(
            service_client.rpc(
                "record_agentcard_refund_result",
                {
                    "target_refund_id": str(result["refund_id"]),
                    "target_provider_refund_id": refund_id,
                    "target_provider_status": provider_status,
                    "provider_result_verified": verified
                    and amount_minor == body.amount_minor
                    and currency == transaction["currency"],
                },
            )
        )
    )
    return ResourceEnvelope(
        data={
            "refund_id": str(result["refund_id"]),
            "provider_refund_id": refund_id,
            "amount_minor": amount_minor,
            "status": result["status"],
        },
        request_id=request.state.request_id,
    )


def process_verified_paypal_webhook(
    client: Client,
    *,
    integration_id: str,
    business_id: str,
    payload: dict[str, Any],
) -> None:
    event_id = payload.get("id")
    event_type = payload.get("event_type")
    resource = payload.get("resource")
    if not isinstance(event_id, str):
        return
    event_key = {"provider": "paypal", "provider_event_id": event_id}
    execute(
        client.table("agentcard_webhook_events").upsert(
            {
                **event_key,
                "event_type": str(event_type or "unknown"),
                "business_id": business_id,
                "signature_verified": True,
                "processing_status": "received",
                "failure_reason": None,
                "processed_at": None,
            },
            on_conflict="provider,provider_event_id",
        )
    )
    if event_type == "PAYMENT.CAPTURE.REFUNDED" and isinstance(resource, dict):
        supplementary = resource.get("supplementary_data")
        related = (
            supplementary.get("related_ids", {})
            if isinstance(supplementary, dict)
            else {}
        )
        capture_id = related.get("capture_id") if isinstance(related, dict) else None
        refund_id = resource.get("id")
        amount = resource.get("amount")
        if (
            not isinstance(capture_id, str)
            or not isinstance(refund_id, str)
            or not isinstance(amount, dict)
        ):
            raise PayPalError("PayPal refund event is incomplete.")
        expected_amount = paypal_amount_to_minor(str(amount.get("value", "")))
        expected_currency = str(amount.get("currency_code", ""))
        payment = execute(
            client.table("agentcard_payments")
            .select("id,business_id,transaction_id")
            .eq("provider", "paypal")
            .eq("provider_capture_id", capture_id)
            .maybe_single()
        )
        if not payment or payment["business_id"] != business_id:
            execute(
                client.table("agentcard_webhook_events")
                .update(
                    {
                        "processing_status": "ignored",
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .match(event_key)
            )
            return
        transaction = execute(
            client.table("agentcard_transactions")
            .select(
                "id,business_id,provider_integration_id,public_transaction_id,status,currency"
            )
            .eq("business_id", payment["business_id"])
            .eq("id", payment["transaction_id"])
            .single()
        )
        if transaction["provider_integration_id"] != integration_id:
            execute(
                client.table("agentcard_webhook_events")
                .update(
                    {
                        "processing_status": "ignored",
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .match(event_key)
            )
            return
        execute(
            client.table("agentcard_webhook_events")
            .update({"transaction_id": transaction["id"]})
            .match(event_key)
        )
        credentials = paypal_credentials(
            client,
            business_id,
            transaction["provider_integration_id"],
        )
        provider_refund = get_paypal_refund(credentials, refund_id)
        verified_id, provider_status, amount_minor, currency, verified = verified_refund_details(
            provider_refund,
            expected_refund_id=refund_id,
            expected_amount_minor=expected_amount,
            expected_currency=expected_currency,
        )
        existing_refund = execute(
            client.table("agentcard_refunds")
            .select("id,business_id,transaction_id")
            .eq("provider_refund_id", verified_id)
            .maybe_single()
        )
        if existing_refund:
            if (
                existing_refund["business_id"] != business_id
                or existing_refund["transaction_id"] != transaction["id"]
            ):
                raise PayPalError("PayPal refund does not match the transaction.")
            refund_record_id = existing_refund["id"]
        else:
            pending_refunds = execute(
                client.table("agentcard_refunds")
                .select("id")
                .eq("business_id", business_id)
                .eq("transaction_id", transaction["id"])
                .eq("amount_minor", amount_minor)
                .eq("currency", currency)
                .eq("status", "pending")
                .is_("provider_refund_id", "null")
                .limit(2)
            )
            if len(pending_refunds) == 1:
                refund_record_id = pending_refunds[0]["id"]
            else:
                refund_record = _record(
                    execute(
                        client.rpc(
                            "start_agentcard_refund",
                            {
                                "target_business_id": business_id,
                                "target_transaction_id": transaction["id"],
                                "target_idempotency_key": f"paypal:{verified_id}",
                                "target_amount_minor": amount_minor,
                                "target_reason": "Refund processed in PayPal",
                            },
                        )
                    )
                )
                refund_record_id = refund_record["refund_id"]
        execute(
            client.rpc(
                "record_agentcard_refund_result",
                {
                    "target_refund_id": refund_record_id,
                    "target_provider_refund_id": verified_id,
                    "target_provider_status": provider_status,
                    "provider_result_verified": verified
                    and currency == transaction["currency"],
                },
            )
        )
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "processed",
                    "failure_reason": None,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        return
    if (
        event_type not in {
            "PAYMENT.CAPTURE.COMPLETED",
            "PAYMENT.CAPTURE.PENDING",
            "PAYMENT.CAPTURE.DENIED",
        }
        or not isinstance(resource, dict)
    ):
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "ignored",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        return
    supplementary = resource.get("supplementary_data")
    related = (
        supplementary.get("related_ids", {})
        if isinstance(supplementary, dict)
        else {}
    )
    provider_order_id = related.get("order_id") if isinstance(related, dict) else None
    if not isinstance(provider_order_id, str):
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "ignored",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        return
    try:
        payment, transaction = transaction_by_provider_order(client, provider_order_id)
    except HTTPException as error:
        if error.status_code != status.HTTP_404_NOT_FOUND:
            raise
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "ignored",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        return
    if payment["business_id"] != business_id or transaction["provider_integration_id"] != integration_id:
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "ignored",
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        return
    execute(
        client.table("agentcard_webhook_events")
        .update({"transaction_id": transaction["id"]})
        .match(event_key)
    )
    try:
        credentials = paypal_credentials(
            client,
            business_id,
            transaction["provider_integration_id"],
        )
        provider_order = get_paypal_order(credentials, provider_order_id)
        order_id, capture_id, amount_minor, currency, verified = verified_capture_details(
            provider_order,
            expected_transaction_id=transaction["public_transaction_id"],
        )
        if resource.get("id") and capture_id and resource["id"] != capture_id:
            verified = False
        target_status = (
            "COMPLETED"
            if verified
            else str(resource.get("status", provider_order.get("status", "PENDING")))
        )
        execute(
            client.rpc(
                "record_agentcard_payment_result",
                {
                    "target_provider_order_id": order_id,
                    "target_provider_capture_id": capture_id or None,
                    "target_provider_status": target_status,
                    "target_amount_minor": amount_minor,
                    "target_currency": currency or transaction["currency"],
                    "provider_result_verified": verified,
                },
            )
        )
    except (HTTPException, PayPalError) as error:
        execute(
            client.table("agentcard_webhook_events")
            .update(
                {
                    "processing_status": "failed",
                    "failure_reason": type(error).__name__,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .match(event_key)
        )
        raise
    execute(
        client.table("agentcard_webhook_events")
        .update(
            {
                "processing_status": "processed",
                "failure_reason": None,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .match(event_key)
    )

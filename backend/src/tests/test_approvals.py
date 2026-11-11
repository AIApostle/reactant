import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.approvals.routes import decide_approval
from src.schemas.approvals import ApprovalDecisionCreate


class ApprovalRouteTests(unittest.TestCase):
    def test_decision_response_ignores_internal_database_fields(self) -> None:
        business_id = uuid4()
        approval_id = uuid4()
        row = {
            "id": str(approval_id),
            "business_id": str(business_id),
            "action_type": "customer_checkout_handoff",
            "status": "approved",
            "impact": {"summary": "Grey Vintage Shirt, quantity 2"},
            "expires_at": None,
            "decided_by": str(uuid4()),
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "decision_note": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": "customer_agent",
            "idempotency_key": "decision-key",
            "request_idempotency_key": "private-request-key",
        }

        with (
            patch("src.approvals.routes.get_business_membership"),
            patch("src.approvals.routes.execute", return_value=row),
        ):
            response = decide_approval(
                business_id=business_id,
                approval_id=approval_id,
                body=ApprovalDecisionCreate(decision="approved"),
                request=SimpleNamespace(state=SimpleNamespace(request_id="request-id")),
                user=SimpleNamespace(id=uuid4()),
                client=MagicMock(),
                idempotency_key="decision-key",
            )

        self.assertEqual(response.data.id, approval_id)
        self.assertEqual(response.data.status, "approved")
        self.assertEqual(response.request_id, "request-id")


if __name__ == "__main__":
    unittest.main()

import unittest
from uuid import uuid4

from pydantic import ValidationError

from src.schemas.conversations import CustomerReplyCreate


class CustomerReplySchemaTests(unittest.TestCase):
    def test_text_or_image_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            CustomerReplyCreate(visibility="customer")

        with self.assertRaises(ValidationError):
            CustomerReplyCreate(visibility="customer", text="  ")

    def test_catalog_image_requires_product_only(self) -> None:
        message = CustomerReplyCreate(
            visibility="customer",
            attachments=[{"source": "catalog", "product_id": str(uuid4())}],
        )
        self.assertEqual(message.attachments[0].source, "catalog")

        with self.assertRaises(ValidationError):
            CustomerReplyCreate(
                visibility="customer",
                text="Here it is",
                attachments=[{"source": "catalog"}],
            )

    def test_reply_image_count_is_bounded(self) -> None:
        with self.assertRaises(ValidationError):
            CustomerReplyCreate(
                visibility="customer",
                attachments=[
                    {"source": "catalog", "product_id": str(uuid4())}
                    for _ in range(4)
                ],
            )


if __name__ == "__main__":
    unittest.main()

import base64
import io
import unittest
from unittest.mock import patch

from PIL import Image

from src.agent.customer_images import (
    CustomerImage,
    decode_customer_image_data_uri,
    history_with_customer_images,
    normalize_customer_image,
    signed_customer_attachments,
)
from src.agent.runtime import invoke_business_agent
from src.widget.routes import WidgetMessageCreate


def _image_bytes(image_format: str = "PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), color=(30, 120, 200)).save(output, format=image_format)
    return output.getvalue()


class CustomerImageTests(unittest.TestCase):
    def test_normalizes_supported_image_to_safe_jpeg(self) -> None:
        image = normalize_customer_image(_image_bytes(), "customer.png")
        self.assertEqual(image.content_type, "image/jpeg")
        self.assertEqual(image.file_name, "customer.jpg")
        with Image.open(io.BytesIO(image.data)) as decoded:
            self.assertEqual(decoded.format, "JPEG")
            self.assertEqual(decoded.size, (32, 24))

    def test_data_uri_requires_valid_supported_image_data(self) -> None:
        encoded = base64.b64encode(_image_bytes()).decode()
        image = decode_customer_image_data_uri(
            f"data:image/png;base64,{encoded}",
            "widget-upload.png",
        )
        self.assertEqual(image.content_type, "image/jpeg")
        with self.assertRaises(ValueError):
            decode_customer_image_data_uri("data:image/svg+xml;base64,PHN2Zz4=")
        with self.assertRaises(ValueError):
            decode_customer_image_data_uri("data:image/png;base64,not-base64")

    def test_website_widget_accepts_image_only_and_text_with_image_messages(self) -> None:
        encoded = base64.b64encode(_image_bytes()).decode()
        data_uri = f"data:image/png;base64,{encoded}"
        image_only = WidgetMessageCreate(images=[data_uri])
        text_and_image = WidgetMessageCreate(
            text="What is in this?",
            images=[data_uri],
        )
        self.assertEqual(image_only.text, "")
        self.assertEqual(text_and_image.text, "What is in this?")
        with self.assertRaises(ValueError):
            WidgetMessageCreate()

    def test_non_image_and_oversized_content_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_customer_image(b"not an image")
        with self.assertRaises(ValueError):
            normalize_customer_image(b"x" * (5 * 1024 * 1024 + 1))

    def test_agent_receives_strands_multimodal_image_block(self) -> None:
        image = normalize_customer_image(_image_bytes("JPEG"))

        class FakeAgent:
            def __init__(self) -> None:
                self.prompt = None

            def __call__(self, prompt, **_kwargs):
                self.prompt = prompt
                return "I can see the image."

        agent = FakeAgent()
        response = invoke_business_agent(
            agent,
            "What is in this picture?",
            audience="customer",
            images=[image],
        )
        self.assertEqual(response, "I can see the image.")
        self.assertEqual(agent.prompt[0], {"text": "What is in this picture?"})
        self.assertEqual(agent.prompt[1], image.agent_content_block())

    def test_customer_image_history_is_loaded_only_for_recent_customer_turns(self) -> None:
        rows = [
            {
                "id": "message-old",
                "sender_type": "customer",
                "text": "Earlier",
                "attachments": [{"type": "image", "storage_path": "b/c/old.jpg"}],
            },
            {"id": "message-agent", "sender_type": "agent", "text": "Reply"},
            {
                "id": "message-new",
                "sender_type": "customer",
                "text": "Another image",
                "attachments": [{"type": "image", "storage_path": "b/c/new.jpg"}],
            },
        ]
        client = object()
        with patch(
            "src.agent.customer_images.load_customer_images",
            side_effect=lambda *_args, **kwargs: [
                CustomerImage(b"image-bytes", "image/jpeg", "image.jpg")
            ],
        ) as load_images:
            history = history_with_customer_images(
                client,
                business_id="b",
                conversation_id="c",
                rows=rows,
                max_history_images=1,
            )
        self.assertEqual([entry["role"] for entry in history], ["user", "assistant", "user"])
        self.assertEqual(len(history[0]["content"]), 1)
        self.assertEqual(history[2]["content"][1]["image"]["source"]["bytes"], b"image-bytes")
        self.assertEqual(load_images.call_count, 1)

    def test_signed_attachments_scope_customer_and_catalog_storage_paths(self) -> None:
        class FakeBucket:
            def create_signed_url(self, path, _ttl):
                return {"signedURL": f"https://media.example/{path}"}

        class FakeStorage:
            def from_(self, bucket):
                self.bucket = bucket
                return FakeBucket()

        class FakeClient:
            storage = FakeStorage()

        attachments = signed_customer_attachments(
            FakeClient(),
            business_id="business-a",
            conversation_id="conversation-a",
            attachments=[
                {
                    "type": "image",
                    "bucket": "customer-chat-media",
                    "storage_path": "business-a/conversation-a/customer.jpg",
                },
                {
                    "type": "image",
                    "bucket": "product-media",
                    "storage_path": "business-a/product.jpg",
                },
                {
                    "type": "image",
                    "bucket": "product-media",
                    "storage_path": "business-b/product.jpg",
                },
            ],
        )

        self.assertEqual(
            [attachment["url"] for attachment in attachments],
            [
                "https://media.example/business-a/conversation-a/customer.jpg",
                "https://media.example/business-a/product.jpg",
            ],
        )


if __name__ == "__main__":
    unittest.main()

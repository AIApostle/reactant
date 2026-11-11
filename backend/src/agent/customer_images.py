import base64
import binascii
import io
import re
import warnings
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from PIL import Image, ImageOps
from supabase import Client


MAX_CUSTOMER_IMAGE_BYTES = 5 * 1024 * 1024
MAX_CUSTOMER_IMAGE_PIXELS = 20_000_000
MAX_CUSTOMER_IMAGES_PER_MESSAGE = 3
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
DATA_URI_PATTERN = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$")


@dataclass(frozen=True)
class CustomerImage:
    data: bytes
    content_type: str
    file_name: str

    @property
    def format(self) -> str:
        return "jpeg"

    def agent_content_block(self) -> dict[str, Any]:
        return {
            "image": {
                "format": self.format,
                "source": {"bytes": self.data},
            }
        }


def normalize_customer_image(data: bytes, file_name: str = "customer-image") -> CustomerImage:
    if not data or len(data) > MAX_CUSTOMER_IMAGE_BYTES:
        raise ValueError("Image must be no larger than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in SUPPORTED_IMAGE_FORMATS:
                    raise ValueError("Only JPEG, PNG, and WebP images are supported.")
                if image.width * image.height > MAX_CUSTOMER_IMAGE_PIXELS:
                    raise ValueError("Image dimensions are too large.")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image = ImageOps.exif_transpose(image)
                if image.width * image.height > MAX_CUSTOMER_IMAGE_PIXELS:
                    raise ValueError("Image dimensions are too large.")
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                if image.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                else:
                    image = image.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=82, optimize=True)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError("Image dimensions are too large.") from error
    except (OSError, SyntaxError) as error:
        raise ValueError("The uploaded image could not be decoded.") from error
    normalized = output.getvalue()
    if len(normalized) > MAX_CUSTOMER_IMAGE_BYTES:
        raise ValueError("The processed image is too large.")
    original_name = file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", original_name)[:100]
    return CustomerImage(
        data=normalized,
        content_type="image/jpeg",
        file_name=f"{safe_name or 'customer-image'}.jpg",
    )


def decode_customer_image_data_uri(data_uri: str, file_name: str = "customer-image") -> CustomerImage:
    match = DATA_URI_PATTERN.fullmatch(data_uri)
    if not match or len(data_uri) > 7_000_000:
        raise ValueError("Send an image as a JPEG, PNG, or WebP data URL.")
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The uploaded image data is invalid.") from error
    return normalize_customer_image(data, file_name)


def store_customer_images(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    images: list[CustomerImage],
) -> list[dict[str, str]]:
    if len(images) > MAX_CUSTOMER_IMAGES_PER_MESSAGE:
        raise ValueError("A message can contain at most three images.")
    total_bytes = sum(len(image.data) for image in images)
    if total_bytes > MAX_CUSTOMER_IMAGE_BYTES:
        raise ValueError("Images in a message cannot exceed 5 MB in total.")
    attachments: list[dict[str, str]] = []
    for image in images:
        path = f"{business_id}/{conversation_id}/{uuid4().hex}.jpg"
        client.storage.from_("customer-chat-media").upload(
            path,
            image.data,
            {"content-type": image.content_type, "upsert": "false"},
        )
        attachments.append(
            {
                "type": "image",
                "storage_path": path,
                "content_type": image.content_type,
                "file_name": image.file_name,
                "alt": "Customer-provided image",
            }
        )
    return attachments


def load_customer_images(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    attachments: list[dict[str, Any]],
) -> list[CustomerImage]:
    images: list[CustomerImage] = []
    for attachment in attachments[:MAX_CUSTOMER_IMAGES_PER_MESSAGE]:
        path = attachment.get("storage_path")
        if (
            attachment.get("type") != "image"
            or not isinstance(path, str)
            or not path.startswith(f"{business_id}/{conversation_id}/")
        ):
            continue
        data = client.storage.from_("customer-chat-media").download(path)
        if not isinstance(data, bytes):
            raise RuntimeError("Stored customer image could not be loaded.")
        images.append(
            normalize_customer_image(
                data,
                str(attachment.get("file_name") or "customer-image"),
            )
        )
    return images


def signed_customer_attachments(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    attachments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    signed_attachments: list[dict[str, Any]] = []
    for source_index, attachment in enumerate(attachments or []):
        if not isinstance(attachment, dict) or attachment.get("type") != "image":
            continue
        existing_url = attachment.get("url")
        path = attachment.get("storage_path")
        if isinstance(existing_url, str) and existing_url.startswith("https://"):
            signed_attachments.append(
                {
                    "type": "image",
                    "url": existing_url,
                    "alt": str(attachment.get("alt") or "Image"),
                    "source_index": source_index,
                }
            )
            continue
        bucket_name = attachment.get("bucket", "customer-chat-media")
        allowed_path = (
            isinstance(path, str)
            and (
                (
                    bucket_name == "customer-chat-media"
                    and path.startswith(f"{business_id}/{conversation_id}/")
                )
                or (
                    bucket_name == "product-media"
                    and path.startswith(f"{business_id}/")
                )
            )
        )
        if not allowed_path:
            continue
        signed = client.storage.from_(bucket_name).create_signed_url(path, 3600)
        url = signed.get("signedURL") or signed.get("signed_url")
        if isinstance(url, str):
            signed_attachments.append(
                {
                    "type": "image",
                    "url": url,
                    "alt": str(attachment.get("alt") or "Customer-provided image"),
                    "source_index": source_index,
                }
            )
    return signed_attachments


def history_with_customer_images(
    client: Client,
    *,
    business_id: str,
    conversation_id: str,
    rows: list[dict[str, Any]],
    max_history_images: int = 2,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    images_loaded = 0
    rows_with_images: set[str] = set()
    remaining_images = max_history_images
    for row in rows:
        attachments = row.get("attachments") or []
        image_count = sum(
            1
            for attachment in attachments
            if isinstance(attachment, dict) and attachment.get("type") == "image"
        )
        if row.get("sender_type") == "customer" and image_count:
            rows_with_images.add(str(row.get("id")))
            remaining_images -= min(image_count, remaining_images)
        if remaining_images <= 0:
            break
    images_loaded = 0
    for row in reversed(rows):
        content: list[dict[str, Any]] = [{"text": str(row.get("text", ""))[:1500]}]
        if (
            row.get("sender_type") == "customer"
            and str(row.get("id")) in rows_with_images
            and images_loaded < max_history_images
        ):
            images = load_customer_images(
                client,
                business_id=business_id,
                conversation_id=conversation_id,
                attachments=row.get("attachments") or [],
            )
            for image in images[: max_history_images - images_loaded]:
                content.append(image.agent_content_block())
                images_loaded += 1
        history.append(
            {
                "role": "assistant" if row["sender_type"] == "agent" else "user",
                "content": content,
            }
        )
    return history

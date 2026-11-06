from typing import Annotated, Literal
from uuid import UUID
from datetime import datetime, timedelta, timezone
from io import BytesIO
import logging
from pathlib import PurePath
import re
import warnings

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from PIL import Image, ImageOps, UnidentifiedImageError
from supabase import Client
from storage3.utils import StorageException

from src.auth.dependencies import AuthenticatedUser, get_current_user
from src.schemas.catalog import (
    MediaAssetResponse,
    MediaUploadCreate,
    MediaUploadResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from src.schemas.common import CollectionEnvelope, PaginationMeta, ResourceEnvelope
from src.supabase.client import get_user_supabase_client
from src.supabase.repository import (
    execute,
    get_business_membership,
    paginated_rows,
    require_role,
)


router = APIRouter()
User = Annotated[AuthenticatedUser, Depends(get_current_user)]
Database = Annotated[Client, Depends(get_user_supabase_client)]
ProductSource = Literal["manual", "woocommerce", "shopify", "all"]
STORAGE_BUCKET = "product-media"
logger = logging.getLogger(__name__)
PRODUCT_FIELDS = (
    "id,business_id,source,name,description,category,price_minor,currency,"
    "stock_quantity,status,agent_enabled,image_asset_ids,created_at,updated_at"
)


def _media_type_from_signature(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _process_uploaded_image(
    content: bytes,
    content_type: str,
) -> tuple[bytes, bytes]:
    expected_format = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }[content_type]
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(content)) as source:
            if source.format != expected_format or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Unsupported image format.")
            if source.width * source.height > 20_000_000:
                raise ValueError("Image dimensions exceed the supported limit.")
            source.verify()
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            if expected_format == "JPEG":
                mode = "RGB"
                if image.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", image.size, "white")
                    alpha = image.getchannel("A")
                    background.paste(image.convert("RGB"), mask=alpha)
                    image = background
                else:
                    image = image.convert(mode)
            elif image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")

            cleaned = Image.new(image.mode, image.size)
            cleaned.paste(image)
            original_buffer = BytesIO()
            cleaned.save(
                original_buffer,
                format=expected_format,
                optimize=True,
                exif=b"",
            )

            delivery = cleaned.copy()
            delivery.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            delivery_buffer = BytesIO()
            delivery.save(
                delivery_buffer,
                format=expected_format,
                optimize=True,
                exif=b"",
            )
    return original_buffer.getvalue(), delivery_buffer.getvalue()


def _validated_assets(
    client: Client,
    business_id: UUID,
    asset_ids: list[UUID],
) -> list[UUID]:
    if len(set(asset_ids)) != len(asset_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "Image assets must not be duplicated."},
        )
    if not asset_ids:
        return asset_ids
    rows = execute(
        client.table("media_assets")
        .select("id")
        .eq("business_id", str(business_id))
        .eq("status", "validated")
        .in_("id", [str(asset_id) for asset_id in asset_ids])
    )
    if {row["id"] for row in rows} != {str(asset_id) for asset_id in asset_ids}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "One or more image assets are unavailable."},
        )
    return asset_ids


@router.get(
    "/businesses/{business_id}/products",
    response_model=CollectionEnvelope[ProductResponse],
)
def list_products(
    business_id: UUID,
    request: Request,
    user: User,
    client: Database,
    q: str | None = Query(default=None, max_length=160),
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    category: str | None = Query(default=None, max_length=120),
    availability: Literal["available", "out_of_stock", "untracked"] | None = None,
    source: ProductSource = "all",
    agent_available: bool | None = None,
) -> CollectionEnvelope[ProductResponse]:
    get_business_membership(client, business_id, user.id)
    query = (
        client.table("products")
        .select(PRODUCT_FIELDS)
        .eq("business_id", str(business_id))
        .neq("status", "archived")
    )
    if q:
        query = query.ilike("name", f"%{q}%")
    if category:
        query = query.eq("category", category)
    if availability == "available":
        query = query.gt("stock_quantity", 0)
    elif availability == "out_of_stock":
        query = query.eq("stock_quantity", 0)
    elif availability == "untracked":
        query = query.is_("stock_quantity", "null")
    if source != "all":
        query = query.eq("source", source)
    if agent_available is not None:
        query = query.eq("agent_enabled", agent_available)
    rows, next_cursor, has_more = paginated_rows(query, cursor=cursor, limit=limit)
    return CollectionEnvelope(
        data=rows,
        meta=PaginationMeta(next_cursor=next_cursor, has_more=has_more),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/products",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[ProductResponse],
)
def create_product(
    business_id: UUID,
    body: ProductCreate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ProductResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    image_asset_ids = _validated_assets(client, business_id, body.image_asset_ids)
    product = execute(
        client.table("products")
        .insert(
            {
                **body.model_dump(exclude={"source"}),
                "business_id": str(business_id),
                "source": "manual",
                "image_asset_ids": [str(asset_id) for asset_id in image_asset_ids],
            }
        )
        .select(PRODUCT_FIELDS)
        .single()
    )
    return ResourceEnvelope(data=ProductResponse(**product), request_id=request.state.request_id)


@router.get(
    "/businesses/{business_id}/products/{product_id}",
    response_model=ResourceEnvelope[ProductResponse],
)
def get_product(
    business_id: UUID,
    product_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ProductResponse]:
    get_business_membership(client, business_id, user.id)
    product = execute(
        client.table("products")
        .select(PRODUCT_FIELDS)
        .eq("business_id", str(business_id))
        .eq("id", str(product_id))
        .maybe_single()
    )
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    return ResourceEnvelope(data=ProductResponse(**product), request_id=request.state.request_id)


@router.patch(
    "/businesses/{business_id}/products/{product_id}",
    response_model=ResourceEnvelope[ProductResponse],
)
def update_product(
    business_id: UUID,
    product_id: UUID,
    body: ProductUpdate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[ProductResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    existing = execute(
        client.table("products")
        .select("source")
        .eq("business_id", str(business_id))
        .eq("id", str(product_id))
        .maybe_single()
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if existing["source"] != "manual":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "provider_managed_product", "message": "Provider-managed products cannot be edited here."},
        )
    changes = body.model_dump(exclude_unset=True)
    if "image_asset_ids" in changes and changes["image_asset_ids"] is not None:
        changes["image_asset_ids"] = [
            str(asset_id)
            for asset_id in _validated_assets(client, business_id, changes["image_asset_ids"])
        ]
    product = execute(
        client.table("products")
        .update(changes)
        .eq("business_id", str(business_id))
        .eq("id", str(product_id))
        .select(PRODUCT_FIELDS)
        .single()
    )
    return ResourceEnvelope(data=ProductResponse(**product), request_id=request.state.request_id)


@router.delete(
    "/businesses/{business_id}/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def archive_product(
    business_id: UUID,
    product_id: UUID,
    user: User,
    client: Database,
) -> None:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    existing = execute(
        client.table("products")
        .select("source")
        .eq("business_id", str(business_id))
        .eq("id", str(product_id))
        .maybe_single()
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if existing["source"] != "manual":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "provider_managed_product", "message": "Provider-managed products cannot be archived here."},
        )
    execute(
        client.table("products")
        .update({"status": "archived", "agent_enabled": False})
        .eq("business_id", str(business_id))
        .eq("id", str(product_id))
    )


@router.post(
    "/businesses/{business_id}/media/uploads",
    status_code=status.HTTP_201_CREATED,
    response_model=ResourceEnvelope[MediaUploadResponse],
)
def create_media_upload(
    business_id: UUID,
    body: MediaUploadCreate,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[MediaUploadResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    file_name = PurePath(body.file_name).name
    if not file_name or re.search(r"[\x00-\x1f\x7f]", file_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "validation_error", "message": "The request could not be completed."},
        )
    asset = execute(
        client.table("media_assets")
        .insert(
            {
                "business_id": str(business_id),
                "storage_path": "pending",
                "file_name": file_name,
                "content_type": body.content_type,
                "size_bytes": body.size_bytes,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            }
        )
        .select("id")
        .single()
    )
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[body.content_type]
    storage_path = f"{business_id}/{asset['id']}.{extension}"
    execute(
        client.table("media_assets")
        .update({"storage_path": storage_path})
        .eq("business_id", str(business_id))
        .eq("id", asset["id"])
    )
    try:
        signed = client.storage.from_(STORAGE_BUCKET).create_signed_upload_url(storage_path)
    except (StorageException, OSError) as error:
        execute(
            client.table("media_assets")
            .delete()
            .eq("business_id", str(business_id))
            .eq("id", asset["id"])
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "storage_unavailable", "message": "The upload could not be prepared right now."},
        ) from error
    return ResourceEnvelope(
        data=MediaUploadResponse(
            asset_id=asset["id"],
            upload_url=signed["signed_url"],
            required_headers={"Content-Type": body.content_type},
            expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
        ),
        request_id=request.state.request_id,
    )


@router.post(
    "/businesses/{business_id}/media/{asset_id}/complete",
    response_model=ResourceEnvelope[MediaAssetResponse],
)
def complete_media_upload(
    business_id: UUID,
    asset_id: UUID,
    request: Request,
    user: User,
    client: Database,
) -> ResourceEnvelope[MediaAssetResponse]:
    membership = get_business_membership(client, business_id, user.id)
    require_role(membership, {"owner", "admin", "staff"})
    asset = execute(
        client.table("media_assets")
        .select("id,business_id,storage_path,file_name,content_type,size_bytes,status,expires_at,created_at")
        .eq("business_id", str(business_id))
        .eq("id", str(asset_id))
        .maybe_single()
    )
    if not asset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "The requested resource was not found."},
        )
    if asset["status"] == "validated":
        return ResourceEnvelope(
            data=MediaAssetResponse(**asset),
            request_id=request.state.request_id,
        )
    if asset.get("expires_at") and datetime.fromisoformat(
        asset["expires_at"].replace("Z", "+00:00")
    ) <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": "upload_expired", "message": "The upload has expired."},
        )
    try:
        content = client.storage.from_(STORAGE_BUCKET).download(asset["storage_path"])
    except (StorageException, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "upload_missing", "message": "The uploaded file could not be validated."},
        ) from error
    actual_type = _media_type_from_signature(content)
    if (
        len(content) != asset["size_bytes"]
        or actual_type != asset["content_type"]
        or len(content) > 5 * 1024 * 1024
    ):
        execute(
            client.table("media_assets")
            .update({"status": "rejected"})
            .eq("business_id", str(business_id))
            .eq("id", str(asset_id))
        )
        try:
            client.storage.from_(STORAGE_BUCKET).remove([asset["storage_path"]])
        except (StorageException, OSError) as error:
            logger.error(
                "Could not remove rejected media asset id=%s error_type=%s",
                asset_id,
                type(error).__name__,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_upload", "message": "The uploaded file is invalid or unsupported."},
        )
    try:
        sanitized_original, delivery_variant = _process_uploaded_image(
            content,
            asset["content_type"],
        )
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        execute(
            client.table("media_assets")
            .update({"status": "rejected"})
            .eq("business_id", str(business_id))
            .eq("id", str(asset_id))
        )
        try:
            client.storage.from_(STORAGE_BUCKET).remove([asset["storage_path"]])
        except (StorageException, OSError) as cleanup_error:
            logger.error(
                "Could not remove rejected media asset id=%s error_type=%s",
                asset_id,
                type(cleanup_error).__name__,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_upload", "message": "The uploaded image could not be decoded safely."},
        ) from error
    extension = {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }[asset["content_type"]]
    delivery_path = f"{business_id}/{asset_id}-delivery.{extension}"
    try:
        bucket = client.storage.from_(STORAGE_BUCKET)
        bucket.upload(
            asset["storage_path"],
            sanitized_original,
            {"content-type": asset["content_type"], "upsert": "true"},
        )
        bucket.upload(
            delivery_path,
            delivery_variant,
            {"content-type": asset["content_type"], "upsert": "true"},
        )
    except (StorageException, OSError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "storage_unavailable", "message": "The uploaded image could not be processed right now."},
        ) from error
    validated = execute(
        client.table("media_assets")
        .update({"status": "validated", "delivery_path": delivery_path})
        .eq("business_id", str(business_id))
        .eq("id", str(asset_id))
        .select("id,business_id,file_name,content_type,size_bytes,status,created_at")
        .single()
    )
    return ResourceEnvelope(
        data=MediaAssetResponse(**validated),
        request_id=request.state.request_id,
    )

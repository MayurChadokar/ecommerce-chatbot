"""Live product details with an explicitly unverified index fallback."""
import os
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from product_availability import availability_fields
from product_index import product_url
from product_pricing import pricing_fields


class ProductDetailInput(BaseModel):
    product_id: int = Field(..., description="ID of the product to fetch details for")
    city: str = Field("INDORE", description="Customer's city; defaults to INDORE")


def fetch_live_details(product_id: int, city: str = "INDORE") -> Dict[str, Any]:
    """Fetch current stock. Auth errors, missing records and timeouts mean unknown."""
    unavailable = {
        "product_id": str(product_id),
        "error": "Live product availability could not be verified. This does not mean out of stock.",
        "error_code": "availability_unverified",
        **availability_fields(city=city),
    }
    token = os.getenv("LOTUS_AUTH_TOKEN", "").strip()
    if not token:
        return unavailable
    try:
        response = requests.post(
            "https://portal.lotuselectronics.com/web-api/home/product_detail",
            headers={"auth-key": "Web2@!9", "auth-token": token, "end-client": "Lotus-Web"},
            data={"product_id": str(product_id), "city": city},
            timeout=(3, 8),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or str(payload.get("error", "0")).lower() not in {"0", "false", "none", ""}:
            return unavailable
        data = payload.get("data")
        detail = data.get("product_detail") if isinstance(data, dict) else None
        if not isinstance(detail, dict) or not detail.get("product_name"):
            return unavailable
        if str(detail.get("product_id")) != str(product_id):
            return unavailable
        images = detail.get("product_image")
        image = (images[0] if images else "") if isinstance(images, list) else (images or "")
        return {
            **{key: detail.get(key) for key in (
                "product_id", "product_name", "uri_slug", "product_sku",
                "product_mrp", "product_msrp", "product_specification", "meta_desc", "del",
            )},
            "product_url": product_url(detail.get("uri_slug"), product_id),
            "product_image": image,
            "source": "live_api",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "price_verified": "selling_price" in pricing_fields(detail),
            "price_source": "live_api" if "selling_price" in pricing_fields(detail) else "unverified",
            **pricing_fields(detail),
            **availability_fields(detail.get("instock"), live=True, city=city),
        }
    except (requests.RequestException, ValueError):
        return unavailable


def _fallback_details(product_id: Any) -> Dict[str, Any]:
    # Never substitute dummy catalog data for a real product, even on matching IDs.
    from tools.product_search_tool import product_search_instance
    record = product_search_instance.get_product_record(product_id)
    if not record:
        return {}
    return {
        "product_id": str(product_id),
        "product_name": record["product_name"],
        "product_mrp": record["price"],
        "product_image": record.get("image_url", ""),
        "product_url": record["product_url"],
        "product_specification": [
            {"fkey": "Highlight", "fvalue": feature} for feature in record.get("features", [])
        ],
        "source": "sql_snapshot",
        **pricing_fields(record),
        **availability_fields(),
    }


@tool("get_filtered_product_details", args_schema=ProductDetailInput, return_direct=False)
def get_filtered_product_details_tool(product_id: int, city: str = "INDORE") -> Dict[str, Any]:
    """Get product details and city-specific live stock. Unknown stock is NOT out of stock.

    An index fallback provides specifications/prices only, never verified availability.
    """
    detail = fetch_live_details(product_id, city)
    if not detail.get("error"):
        return detail
    fallback = _fallback_details(product_id)
    if fallback:
        fallback.update(availability_fields(city=city))
        fallback["availability_message"] = detail["error"]
        from live_product_enrichment import enabled, merge_live, live_card_fields
        if enabled():
            fallback = merge_live(fallback, None, city)
            fallback.update(live_card_fields(fallback))
        return fallback
    return detail

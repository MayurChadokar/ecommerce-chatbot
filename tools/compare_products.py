"""Tool: compare two products spec-by-spec.

Self-sufficient: resolves each product id from the local catalog first, then
falls back to the live product-detail API. This means the assistant only needs a
SINGLE tool call to compare — it should never fetch details one-by-one, which was
causing tool-call loops.
"""

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import tool

import catalog
from product_pricing import pricing_fields
from tools.Product_details import get_filtered_product_details_tool
from live_product_enrichment import enabled as live_enabled
from product_pricing import price_number

# Only keep a handful of meaningful spec rows from the (often noisy) live API
_MAX_LIVE_SPECS = 8


class CompareInput(BaseModel):
    city: str = Field("INDORE", min_length=1, max_length=100, description="Customer city for live verification")
    product_ids: List[int] = Field(
        ...,
        description="List of exactly two product IDs to compare, e.g. [39422, 39831]",
    )


def _parse_price(value: Any) -> Optional[int]:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def _normalize_live(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a live product_detail dict into the record shape build_comparison needs."""
    name = detail.get("product_name") or "Product"
    specs: Dict[str, str] = {}
    raw_specs = detail.get("product_specification")
    if isinstance(raw_specs, list):
        for spec in raw_specs:
            if not isinstance(spec, dict):
                continue
            key = (spec.get("fkey") or "").strip()
            val = (spec.get("fvalue") or "").strip()
            if key and val and key not in specs:
                specs[key] = val
            if len(specs) >= _MAX_LIVE_SPECS:
                break
    return {
        "product_name": name,
        "brand": name.split()[0] if name else "Product",
        "price": price_number(detail.get("selling_price") or detail.get("product_mrp")) if live_enabled() else _parse_price(detail.get("product_mrp")),
        "image": detail.get("product_image") or "",
        "specs": specs,
        **pricing_fields(detail),
    }


def _resolve(product_id: Any, city: str = "INDORE") -> Optional[Dict[str, Any]]:
    """Resolve a product record for comparison.

    Order: static catalog (rich specs) -> products the user has already seen in
    search/browse (name/price/features) -> live detail API. This makes comparison
    work for any product the customer has actually been shown.
    """
    if live_enabled():
        # A demo record must not shadow a real product with the same ID.
        detail = get_filtered_product_details_tool.invoke({"product_id": int(product_id), "city": city})
        return _normalize_live(detail) if isinstance(detail, dict) and not detail.get("error") else None
    record = catalog.get_product(product_id)
    if record:
        return record

    seen = catalog.get_seen(product_id)

    # Try to enrich with live specs; fall back to the seen record if that fails
    try:
        pid_int = int(float(product_id))  # tolerate "39721.0" / 39721.0
        detail = get_filtered_product_details_tool.invoke({"product_id": pid_int})
        if isinstance(detail, dict) and not detail.get("error"):
            return _normalize_live(detail)
    except Exception:
        pass

    return seen


@tool("compare_products", args_schema=CompareInput, return_direct=False)
def compare_products_tool(product_ids: List[int], city: str = "INDORE") -> Dict[str, Any]:
    """
    Compare two products side by side in ONE call.

    Provide exactly two product_ids (extract them from the previous search results).
    This tool fetches each product's details itself, so do NOT call
    get_filtered_product_details separately when comparing. Returns a structured
    comparison with a spec table, key differences, and a value verdict.
    """
    if not product_ids or len(product_ids) < 2:
        return {"error": "Please provide two product IDs to compare."}

    a = _resolve(product_ids[0], city)
    b = _resolve(product_ids[1], city)
    if not a or not b:
        missing = product_ids[0] if not a else product_ids[1]
        return {"error": f"I couldn't find enough details for product {missing} to compare."}

    return catalog.build_comparison(a, b)

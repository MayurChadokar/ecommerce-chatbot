"""Request-time product verification. No vector writes or price/stock cache."""
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
import math
import json
import os
import threading

from product_availability import availability_fields
from product_pricing import price_number, pricing_fields

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="lotus-live")
_slots = threading.BoundedSemaphore(24)
PRICE_FIELDS = ("price", "product_mrp", "product_msrp", "selling_price", "mrp",
                "store_offer_price", "eff_price", "discount_amount", "discount_percent")
VERIFICATION_NOTICE = {
    "title": "Verify live price & stock",
    "message": "Live price or stock could not be verified for some products. "
               "Catalogue prices are last-known and may change. "
               "Use View product to confirm the current price and availability before buying.",
}


def enabled():
    return os.getenv("LOTUS_LIVE_ENRICHMENT", "false").lower() == "true"


def deadline_seconds():
    try:
        value = float(os.getenv("LOTUS_LIVE_ENRICHMENT_TIMEOUT", "6"))
        return value if math.isfinite(value) and 0 < value <= 30 else 6.0
    except ValueError:
        return 6.0


class LiveResults(list):
    """Keep verification/error metadata request-local, including empty results."""
    def __init__(self, records, metadata, error=None):
        super().__init__(records)
        self.verification = metadata
        self.verification_error = error


def merge_live(record, detail, city):
    result = dict(record)
    catalogue_price = price_number(record.get("selling_price")) or price_number(record.get("price")) or price_number(record.get("product_mrp"))
    result["snapshot_instock"] = record.get("instock", "Unknown")
    for key in PRICE_FIELDS:
        result.pop(key, None)
    result.update(price=None, price_verified=False, price_source="unverified",
                  live_checked=True, source="sql_snapshot",
                  catalogue_price=catalogue_price, catalogue_fallback=True,
                  verification_message="Current price and stock could not be verified.",
                  **availability_fields(city=city))
    if not isinstance(detail, dict) or detail.get("error"):
        return result
    if str(detail.get("product_id")) != str(record["product_id"]):
        return result
    if detail.get("source") != "live_api":
        return result
    old_sku, new_sku = str(record.get("sku") or "").strip(), str(detail.get("product_sku") or "").strip()
    if old_sku and new_sku and old_sku.casefold() != new_sku.casefold():
        return result
    if detail.get("stock_city") != city:
        return result
    result.update(source="live_api", checked_at=detail.get("checked_at") or datetime.now(timezone.utc).isoformat())
    result.update(availability_fields(detail.get("instock"), live=True, city=city))
    # Only the current API price can become a current card/filter price.
    price = price_number(detail.get("selling_price"))
    if price is not None:
        result.update(pricing_fields(detail))
        result.update(price=price, price_verified=True, price_source="live_api")
    if result["price_verified"] and result["stock_verified"]:
        result.pop("verification_message", None)
        result.pop("catalogue_price", None)
        result.pop("catalogue_fallback", None)
    else:
        result["verification_message"] = "Some current price or stock information could not be verified."
    return result


def enrich(records, *, top_k, city, price_min=None, price_max=None, fetch=None):
    if fetch is None:
        from tools.Product_details import fetch_live_details
        fetch = fetch_live_details
    # Overfetch a few candidates for live budget checks, never scan the catalogue.
    candidates = records[:min(20, max(top_k, 10))]
    pending = {}
    details = {}
    for position, record in enumerate(candidates):
        if not _slots.acquire(blocking=False):
            continue
        try:
            future = _pool.submit(fetch, int(record["product_id"]), city)
            future.add_done_callback(lambda _: _slots.release())
            pending[future] = position
        except Exception:
            _slots.release()
    if pending:
        done, unfinished = wait(pending, timeout=deadline_seconds())
        for future in done:
            try:
                details[pending[future]] = future.result()
            except Exception:
                pass
        for future in unfinished:
            future.cancel()
        # Do not wait for slow requests. Running calls have HTTP timeouts and
        # retain their capacity slot until actually finished; no unbounded queue.
    merged = [merge_live(record, details.get(i), city) for i, record in enumerate(candidates)]
    unknown_price = sum(not r["price_verified"] for r in merged)
    unknown_stock = sum(not r["stock_verified"] for r in merged)
    budget = price_min is not None or price_max is not None
    def budget_match(record):
        # A catalogue price can suggest options during an outage, never confirm
        # a current budget match or override a successfully verified live price.
        price = record["price"] if record["price_verified"] else record.get("catalogue_price")
        return price is not None and (price_min is None or price >= price_min) and (price_max is None or price <= price_max)

    filtered = [r for r in merged if not budget or budget_match(r)]
    if budget and unknown_price and not filtered:
        # During an outage, also use the remaining already-retrieved Pinecone
        # candidates. No additional API calls or catalogue-wide scan are made.
        extra = [merge_live(r, None, city) for r in records[len(candidates):20]]
        filtered.extend(r for r in extra if budget_match(r))
        candidates.extend(records[len(candidates):20])
        unknown_price += len(extra)
        unknown_stock += len(extra)
    error = "Current prices could not be verified for some candidates; budget matches are incomplete." if budget and unknown_price and not filtered else None
    return LiveResults(filtered[:top_k], {
        "enabled": True, "city": city, "candidate_count": len(candidates),
        "price_unverified_count": unknown_price, "stock_unverified_count": unknown_stock,
        "complete": unknown_price == 0 and unknown_stock == 0,
        "catalogue_fallback_count": sum(bool(r.get("catalogue_fallback")) for r in filtered[:top_k]),
        "scope": "retrieved_candidates_only", "cached": False,
    }, error)


def live_card_fields(record):
    """Overlay existing card fields; never expose an old price as current."""
    if not record.get("live_checked"):
        return {}
    fields = {key: record[key] for key in (
        "instock", "availability_status", "stock_verified", "stock_source", "stock_city",
        "price_verified", "price_source", "source", "checked_at", "verification_message",
        "snapshot_instock",
        "catalogue_fallback", "catalogue_price",
    ) if key in record}
    fields["product_mrp"] = f"₹{record['price']:,.2f}" if record.get("price_verified") else "Price unavailable"
    if not record.get("price_verified") and record.get("catalogue_price") is not None:
        fields["price_source"] = "sql_snapshot"
    return fields


def collect_live_products(messages):
    """Only current-turn tool facts; never reuse an old assistant's price."""
    products = {}
    for message in messages:
        if getattr(message, "type", None) == "human":
            products = {}
        if getattr(message, "type", None) != "tool":
            continue
        if getattr(message, "name", "") not in {"search_products", "browse_catalog", "recommend_products", "get_filtered_product_details"}:
            continue
        try:
            payload = message.content
            payload = json.loads(payload) if isinstance(payload, str) else payload
        except (TypeError, ValueError):
            continue
        rows = payload if isinstance(payload, list) else payload.get("products", [payload]) if isinstance(payload, dict) else []
        if isinstance(payload, dict) and isinstance(payload.get("catalogue_products"), list):
            rows = list(rows) + payload["catalogue_products"] if isinstance(rows, list) else payload["catalogue_products"]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("product_id") and "price_verified" in row:
                products[str(row["product_id"])] = dict(row)
    return products


def normalize_live_response(response, products):
    """Pin structured cards to backend facts before they are displayed or saved."""
    def normalize(card):
        if not isinstance(card, dict):
            return card
        pid = str(card.get("product_id", ""))
        if pid in products:
            return dict(products[pid])
        result = dict(card)
        for field in (*PRICE_FIELDS, "sale_price", "product_selling_price", "catalogue_price", "catalogue_fallback"):
            result.pop(field, None)
        result.update(product_mrp="Price unavailable", price_verified=False,
                      price_source="unverified", **availability_fields())
        return result
    result = dict(response)
    result.pop("verification_notice", None)  # Notices must come from backend facts.
    for key in ("products", "recommendations"):
        if isinstance(result.get(key), list):
            result[key] = [normalize(card) for card in result[key]
                           if isinstance(card, dict) and (not products or str(card.get("product_id")) in products)]
    if isinstance(result.get("product_details"), dict) and result["product_details"]:
        result["product_details"] = normalize(result["product_details"])
    fallback_products = [dict(p) for p in products.values() if p.get("catalogue_fallback")]
    if fallback_products:
        # Keep real catalogue cards and links even if the model returns only a
        # generic apology. Facts come from this turn's tools, never old history.
        shown = {str(p.get("product_id")) for key in ("products", "recommendations")
                 for p in (result.get(key) or []) if isinstance(p, dict)}
        detail = result.get("product_details")
        if isinstance(detail, dict) and detail.get("product_id"):
            shown.add(str(detail["product_id"]))
        missing = [p for p in fallback_products if str(p["product_id"]) not in shown]
        if missing:
            if not isinstance(result.get("products"), list):
                result["products"] = []
            result["products"].extend(missing)
        result["verification_notice"] = dict(VERIFICATION_NOTICE)
        if not any(result.get(key) for key in ("stores", "policy_info", "comparison", "order", "ticket", "bulk_enquiry")):
            result["answer"] = "Here are product options from our catalogue. Some live price or stock checks could not be completed; catalogue prices are last-known and availability is unconfirmed where indicated."
            result["end"] = "Use View product to verify the current price and stock before buying."
    return result

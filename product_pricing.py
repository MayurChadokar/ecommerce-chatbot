"""Lotus price mapping, verified against the storefront's product-detail display.

product_msrp = list MRP; product_mrp = online selling price.
eff_price is a separate, conditional in-store offer, never the online price.
"""
import re
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP


def price_number(value):
    if value is None or isinstance(value, bool):
        return None
    text = re.sub(r"^(?:₹|INR|Rs\.?)\s*", "", str(value).strip(), flags=re.I)
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?", text):
        return None
    try:
        amount = Decimal(text.replace(",", ""))
        if not amount.is_finite() or amount <= 0:
            return None
        return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return None


def _first(*values):
    return next((price for value in values if (price := price_number(value)) is not None), None)


def pricing_fields(record):
    """Return explicit UI fields, without inventing missing MRP or discounts."""
    mrp = _first(record.get("mrp"), record.get("product_msrp"))
    selling = _first(record.get("selling_price"), record.get("product_mrp"))
    if selling is None and record.get("price_field") == "product_mrp":
        selling = price_number(record.get("price"))
    offer = _first(record.get("store_offer_price"), record.get("eff_price"))
    result = {key: value for key, value in (
        ("mrp", mrp), ("selling_price", selling), ("store_offer_price", offer)
    ) if value is not None}
    if mrp is not None and selling is not None and mrp >= selling:
        saving = Decimal(str(mrp)) - Decimal(str(selling))
        result["discount_amount"] = float(saving)
        result["discount_percent"] = float((saving * 100 / Decimal(str(mrp))).quantize(
            Decimal("0.1"), rounding=ROUND_DOWN))
    return result


def pricing_metadata(record):
    """Add raw and normalized prices to Pinecone; omit null metadata values."""
    values = {field: price_number(record.get(field)) for field in (
        "product_msrp", "product_mrp", "wprice2", "eff_price"
    )}
    result = {key: value for key, value in values.items() if value is not None}
    result.update(pricing_fields(values))
    result["pricing_schema"] = "lotus-v1"
    return result

"""Explicit stock states: a failed lookup is never evidence of no stock."""


def stock_status(value):
    value = str(value).strip().lower()
    if value in {"yes", "true", "1", "in stock", "in_stock"}:
        return "in_stock"
    if value in {"no", "false", "0", "out of stock", "out_of_stock"}:
        return "out_of_stock"
    return "unknown"


def availability_fields(value=None, *, live=False, city=None):
    status = stock_status(value) if live else "unknown"
    return {
        "instock": {"in_stock": "Yes", "out_of_stock": "No"}.get(status, "Unknown"),
        "availability_status": status,
        "stock_verified": status != "unknown",
        "stock_source": "live_api" if live else "unverified",
        "stock_city": city,
    }

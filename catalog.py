"""
Local dummy product catalog for Lotus Electronics.

The live product-detail API token is expired, so comparison, recommendation and
order features read from this in-memory catalog instead. Product field names match
what `tools/product_search_tool.py` returns (product_id, product_name, product_mrp,
product_url, product_image, features) so the frontend renders everything the same
way. Some IDs intentionally overlap the real search results (e.g. 39422, 39831).
"""

from typing import Any, Dict, List, Optional
from product_pricing import pricing_fields

_IMG = "https://cdn.lotuselectronics.com/webpimages"

# Each product: numeric-string product_id, price is an int (rupees).
_CATALOG: List[Dict[str, Any]] = [
    {
        "product_id": "39422",
        "product_name": "Redmi 14C 5G (4GB RAM, 64GB Storage) Stargaze Black",
        "brand": "Redmi",
        "category": "smartphone",
        "price": 9499,
        "image": f"{_IMG}/7045810IM.webp",
        "specs": {
            "Display": "6.88 inch HD+ 120Hz",
            "Processor": "Snapdragon 4s Gen 2",
            "RAM": "4GB",
            "Storage": "64GB",
            "Battery": "5160 mAh",
            "Rear Camera": "50MP",
            "Network": "5G",
            "Warranty": "1 Year",
        },
        "features": ["5G connectivity", "120Hz display", "50MP camera", "5160 mAh battery"],
    },
    {
        "product_id": "39831",
        "product_name": "Redmi A5 4G (4GB RAM, 128GB ROM) Jaisalmer Gold",
        "brand": "Redmi",
        "category": "smartphone",
        "price": 7499,
        "image": f"{_IMG}/718961IM.webp",
        "specs": {
            "Display": "6.88 inch HD+ 120Hz",
            "Processor": "Octa Core",
            "RAM": "4GB",
            "Storage": "128GB",
            "Battery": "5200 mAh",
            "Rear Camera": "32MP",
            "Network": "4G",
            "Warranty": "1 Year",
        },
        "features": ["128GB storage", "Large 5200 mAh battery", "32MP camera", "Octa Core"],
    },
    {
        "product_id": "40089",
        "product_name": "Samsung Galaxy A26 5G (6GB RAM, 128GB Storage) White",
        "brand": "Samsung",
        "category": "smartphone",
        "price": 21557,
        "image": f"{_IMG}/722651IM.webp",
        "specs": {
            "Display": "6.7 inch Super AMOLED 120Hz",
            "Processor": "Exynos 1380",
            "RAM": "6GB",
            "Storage": "128GB",
            "Battery": "5000 mAh",
            "Rear Camera": "50MP OIS",
            "Network": "5G",
            "Warranty": "1 Year",
        },
        "features": ["Super AMOLED display", "50MP OIS camera", "5G", "IP67 water resistant"],
    },
    {
        "product_id": "38210",
        "product_name": "OnePlus Nord CE4 Lite 5G (8GB RAM, 128GB Storage) Mega Blue",
        "brand": "OnePlus",
        "category": "smartphone",
        "price": 19999,
        "image": f"{_IMG}/731201IM.webp",
        "specs": {
            "Display": "6.67 inch AMOLED 120Hz",
            "Processor": "Snapdragon 695",
            "RAM": "8GB",
            "Storage": "128GB",
            "Battery": "5500 mAh",
            "Rear Camera": "50MP",
            "Network": "5G",
            "Warranty": "1 Year",
        },
        "features": ["8GB RAM", "5500 mAh battery", "80W fast charge", "AMOLED 120Hz"],
    },
    {
        "product_id": "38455",
        "product_name": "iPhone 15 (128GB) Blue",
        "brand": "Apple",
        "category": "smartphone",
        "price": 65999,
        "image": f"{_IMG}/700011IM.webp",
        "specs": {
            "Display": "6.1 inch Super Retina XDR",
            "Processor": "A16 Bionic",
            "RAM": "6GB",
            "Storage": "128GB",
            "Battery": "3349 mAh",
            "Rear Camera": "48MP Dual",
            "Network": "5G",
            "Warranty": "1 Year",
        },
        "features": ["A16 Bionic chip", "48MP camera", "Dynamic Island", "iOS 17"],
    },
    {
        "product_id": "41002",
        "product_name": "Samsung 108cm (43 inch) 4K Ultra HD Smart LED TV",
        "brand": "Samsung",
        "category": "television",
        "price": 32990,
        "image": f"{_IMG}/650101IM.webp",
        "specs": {
            "Screen Size": "43 inch",
            "Resolution": "4K Ultra HD",
            "Panel": "LED",
            "Refresh Rate": "60Hz",
            "Smart OS": "Tizen",
            "HDMI Ports": "3",
            "Warranty": "1 Year",
        },
        "features": ["4K Ultra HD", "Tizen Smart TV", "HDR10+", "3 HDMI ports"],
    },
    {
        "product_id": "41055",
        "product_name": "LG 139cm (55 inch) 4K OLED Smart TV",
        "brand": "LG",
        "category": "television",
        "price": 99990,
        "image": f"{_IMG}/651201IM.webp",
        "specs": {
            "Screen Size": "55 inch",
            "Resolution": "4K Ultra HD",
            "Panel": "OLED",
            "Refresh Rate": "120Hz",
            "Smart OS": "webOS",
            "HDMI Ports": "4",
            "Warranty": "1 Year",
        },
        "features": ["OLED panel", "120Hz refresh", "Dolby Vision IQ", "webOS"],
    },
    {
        "product_id": "42010",
        "product_name": "HP Pavilion 15 (Intel Core i5, 16GB RAM, 512GB SSD)",
        "brand": "HP",
        "category": "laptop",
        "price": 61990,
        "image": f"{_IMG}/660301IM.webp",
        "specs": {
            "Processor": "Intel Core i5 13th Gen",
            "RAM": "16GB",
            "Storage": "512GB SSD",
            "Display": "15.6 inch FHD",
            "Graphics": "Intel Iris Xe",
            "OS": "Windows 11",
            "Warranty": "1 Year",
        },
        "features": ["13th Gen Core i5", "16GB RAM", "512GB SSD", "FHD display"],
    },
    {
        "product_id": "42077",
        "product_name": "Lenovo IdeaPad Slim 3 (AMD Ryzen 5, 8GB RAM, 512GB SSD)",
        "brand": "Lenovo",
        "category": "laptop",
        "price": 46990,
        "image": f"{_IMG}/661101IM.webp",
        "specs": {
            "Processor": "AMD Ryzen 5 7530U",
            "RAM": "8GB",
            "Storage": "512GB SSD",
            "Display": "15.6 inch FHD",
            "Graphics": "AMD Radeon",
            "OS": "Windows 11",
            "Warranty": "1 Year",
        },
        "features": ["Ryzen 5", "8GB RAM", "512GB SSD", "Lightweight"],
    },
    {
        "product_id": "43001",
        "product_name": "LG 1.5 Ton 5 Star Dual Inverter Split AC",
        "brand": "LG",
        "category": "ac",
        "price": 42990,
        "image": f"{_IMG}/670101IM.webp",
        "specs": {
            "Capacity": "1.5 Ton",
            "Star Rating": "5 Star",
            "Type": "Split Inverter",
            "Compressor": "Dual Inverter",
            "Cooling": "18000 BTU",
            "Warranty": "1 Yr unit, 10 Yr compressor",
        },
        "features": ["5 Star rating", "Dual Inverter", "Copper condenser", "Low noise"],
    },
    {
        "product_id": "43044",
        "product_name": "Voltas 1.5 Ton 3 Star Split AC",
        "brand": "Voltas",
        "category": "ac",
        "price": 32990,
        "image": f"{_IMG}/671201IM.webp",
        "specs": {
            "Capacity": "1.5 Ton",
            "Star Rating": "3 Star",
            "Type": "Split Inverter",
            "Compressor": "Inverter",
            "Cooling": "17500 BTU",
            "Warranty": "1 Yr unit, 10 Yr compressor",
        },
        "features": ["3 Star", "Turbo cooling", "Copper condenser", "Anti-dust filter"],
    },
    {
        "product_id": "44012",
        "product_name": "boAt Airdopes 141 Wireless Earbuds",
        "brand": "boAt",
        "category": "audio",
        "price": 1499,
        "image": f"{_IMG}/680101IM.webp",
        "specs": {
            "Type": "TWS Earbuds",
            "Battery": "42 Hrs playback",
            "Driver": "8mm",
            "Bluetooth": "5.1",
            "Charging": "Type-C",
            "Warranty": "1 Year",
        },
        "features": ["42H playback", "ENx tech", "Low latency", "IPX4"],
    },
]

# Fast lookup by id
_BY_ID: Dict[str, Dict[str, Any]] = {p["product_id"]: p for p in _CATALOG}

# Runtime cache of products the user has actually been shown (from live search /
# browse), so comparison works for real inventory ids that aren't in the static
# catalog. Keyed by normalized product_id.
_SEEN: Dict[str, Dict[str, Any]] = {}


def _parse_price_str(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    import re
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def remember_products(products: Any) -> None:
    """Cache a list of shown product dicts for later comparison/lookup."""
    if not isinstance(products, list):
        return
    for p in products:
        if not isinstance(p, dict):
            continue
        pid = p.get("product_id") or p.get("id")
        if not pid:
            continue
        name = p.get("product_name") or p.get("name") or "Product"
        _SEEN[_norm_id(pid)] = {
            "product_name": name,
            "brand": name.split()[0] if name else "Product",
            "price": _parse_price_str(p.get("product_mrp") or p.get("price")),
            "image": p.get("product_image") or p.get("image") or "",
            "specs": {},
            "features": p.get("features") or [],
            **pricing_fields(p),
        }


def get_seen(product_id: Any) -> Optional[Dict[str, Any]]:
    """Return a previously-shown product record by id, or None."""
    return _SEEN.get(_norm_id(product_id))


def _fmt_price(price: int) -> str:
    return f"₹{price:,.0f}"


def _public_view(p: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a catalog record into the product object the frontend expects."""
    return {
        "product_id": p["product_id"],
        "product_name": p["product_name"],
        "product_mrp": _fmt_price(p["price"]),
        "product_image": p["image"],
        "product_url": f"https://www.lotuselectronics.com/product/{p['product_id']}",
        "features": p["features"],
    }


def _norm_id(product_id: Any) -> str:
    """Normalize an id to a plain string, tolerating floats like 39721.0."""
    if isinstance(product_id, float):
        return str(int(product_id))
    s = str(product_id).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def get_product(product_id: Any) -> Optional[Dict[str, Any]]:
    """Return the raw catalog record for an id, or None."""
    return _BY_ID.get(_norm_id(product_id))


def get_product_view(product_id: Any) -> Optional[Dict[str, Any]]:
    """Return the frontend-facing product object for an id, or None."""
    p = get_product(product_id)
    return _public_view(p) if p else None


def find_by_category(category: str, budget: Optional[float] = None) -> List[Dict[str, Any]]:
    cat = (category or "").lower().strip()
    matches = [p for p in _CATALOG if p["category"] == cat]
    if budget:
        matches = [p for p in matches if p["price"] <= float(budget)]
    return matches


# Map common user words to catalog categories
_CATEGORY_ALIASES = {
    "phone": "smartphone", "smartphone": "smartphone", "mobile": "smartphone",
    "tv": "television", "television": "television", "led": "television",
    "laptop": "laptop", "notebook": "laptop", "computer": "laptop",
    "ac": "ac", "air conditioner": "ac", "airconditioner": "ac",
    "audio": "audio", "earbuds": "audio", "earphone": "audio",
    "headphone": "audio", "speaker": "audio",
}


def resolve_category(text: Optional[str]) -> Optional[str]:
    """Map a free-text term to a known catalog category, if possible."""
    if not text:
        return None
    t = text.lower().strip()
    if t in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[t]
    for word, cat in _CATEGORY_ALIASES.items():
        if word in t:
            return cat
    return None


def browse(
    category: Optional[str] = None,
    budget: Optional[float] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Return frontend-facing products from the catalog, optionally filtered."""
    cat = resolve_category(category) if category else None
    if cat:
        pool = find_by_category(cat, budget)
    else:
        pool = [p for p in _CATALOG if (budget is None or p["price"] <= float(budget))]
    pool = sorted(pool, key=lambda p: p["price"])
    return [_public_view(p) for p in pool[:limit]]


def recommend(
    based_on_id: Optional[Any] = None,
    category: Optional[str] = None,
    budget: Optional[float] = None,
    exclude: Optional[List[Any]] = None,
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Recommend products by category/budget, or similar to a given product."""
    exclude_ids = {str(x) for x in (exclude or [])}

    base = get_product(based_on_id) if based_on_id else None
    if base:
        category = category or base["category"]
        exclude_ids.add(base["product_id"])
        # Default budget window around the base product if none supplied
        if budget is None:
            budget = base["price"] * 1.6

    if category:
        pool = find_by_category(category, budget)
    else:
        pool = [p for p in _CATALOG if (budget is None or p["price"] <= float(budget))]

    pool = [p for p in pool if p["product_id"] not in exclude_ids]
    # Cheapest-first tends to read as good value in a sales context
    pool.sort(key=lambda p: p["price"])
    return [_public_view(p) for p in pool[:limit]]


def build_comparison(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Build a spec-by-spec comparison from two normalized product records.

    Each record needs: product_name, brand, price (int or None), image, specs(dict).
    Returns name/vs_name, a human-readable `differences` list, a `spec_table`
    (rows of {feature, a, b}) and a simple `verdict`.
    """
    a_specs = a.get("specs") or {}
    b_specs = b.get("specs") or {}
    keys: List[str] = list(a_specs.keys())
    for k in b_specs:
        if k not in keys:
            keys.append(k)

    spec_table = []
    differences = []
    price_a = a.get("price")
    price_b = b.get("price")
    spec_table.append({
        "feature": "Price",
        "a": _fmt_price(price_a) if price_a else "-",
        "b": _fmt_price(price_b) if price_b else "-",
    })
    for k in keys:
        av = a_specs.get(k, "-")
        bv = b_specs.get(k, "-")
        spec_table.append({"feature": k, "a": av, "b": bv})
        if av != bv and av not in ("-", "", None) and bv not in ("-", "", None):
            differences.append(
                f"{k}: {a.get('brand', 'Option A')} has {av} vs "
                f"{b.get('brand', 'Option B')} {bv}"
            )

    # When structured specs are thin, fall back to price + feature highlights so
    # the comparison is still informative for real search-result products.
    if price_a and price_b and price_a != price_b:
        diff = abs(price_a - price_b)
        cheaper_name = a["product_name"] if price_a < price_b else b["product_name"]
        differences.insert(0, f"Price: {cheaper_name} is {_fmt_price(diff)} cheaper.")
    a_feats = a.get("features") or []
    b_feats = b.get("features") or []
    if not a_specs and a_feats:
        differences.append(f"{a.get('brand', 'Option A')} highlights: {', '.join(a_feats[:3])}")
    if not b_specs and b_feats:
        differences.append(f"{b.get('brand', 'Option B')} highlights: {', '.join(b_feats[:3])}")

    verdict = "Both products are strong choices — pick based on the features you value most."
    if price_a and price_b:
        cheaper = a if price_a <= price_b else b
        verdict = (
            f"{cheaper['product_name']} is the more budget-friendly option at "
            f"{_fmt_price(cheaper['price'])}."
        )

    return {
        "name": a.get("product_name", "Product A"),
        "vs_name": b.get("product_name", "Product B"),
        "price_a": _fmt_price(price_a) if price_a else "-",
        "price_b": _fmt_price(price_b) if price_b else "-",
        "image_a": a.get("image", ""),
        "image_b": b.get("image", ""),
        "differences": differences or ["Both products share very similar specifications."],
        "spec_table": spec_table,
        "verdict": verdict,
        **{f"{key}_{side}": value for side, product in (("a", a), ("b", b))
           for key, value in pricing_fields(product).items()},
    }


def compare(id_a: Any, id_b: Any) -> Dict[str, Any]:
    """Compare two catalog products by id (falls back with a clear error)."""
    a = get_product(id_a)
    b = get_product(id_b)
    if not a or not b:
        missing = id_a if not a else id_b
        return {"error": f"Product {missing} is not in our catalog for comparison."}
    return build_comparison(a, b)

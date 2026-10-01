"""Extract allowlisted product data from a MySQL dump WITHOUT executing SQL.

Run from the project directory: python -m scripts.extract_products --help
Only four exact table names are read; archives, users, payments and orders are
never exported. Outputs are new files only, to avoid overwriting previous runs.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re

from product_index import EMBEDDING_MODEL, product_url
from product_pricing import pricing_metadata

TABLES = {"les_products", "les_product_features", "les_brand", "les_category"}
INSERT = re.compile(r"^INSERT INTO `([^`]+)`\s*\((.*?)\)\s*VALUES\s*(.*)$")
PRICE_FIELDS = ("product_mrp", "eff_price", "wprice2", "product_msrp")
ESCAPES = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a"}


class ValuesParser:
    """Incremental parser for mysqldump literal VALUES, including escaped SQL strings."""

    def __init__(self):
        self.in_string = False
        self.pending_quote = False
        self.escape = False
        self.row = None
        self.token = []
        self.quoted = False
        self.done = False

    def finish_value(self):
        raw = "".join(self.token)
        if self.quoted:
            value = raw
        elif raw.strip().upper() == "NULL":
            value = None
        elif re.fullmatch(r"0x[0-9a-fA-F]*", raw.strip()):
            value = bytes.fromhex(raw.strip()[2:]).decode("utf-8", errors="replace")
        elif re.fullmatch(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", raw.strip()):
            value = raw.strip()
        else:
            raise ValueError("Unsupported SQL value; dump was not executed")
        self.row.append(value)
        self.token = []
        self.quoted = False

    def feed(self, fragment):
        for char in fragment:
            if self.done:
                if not char.isspace():
                    raise ValueError("Unexpected content after SQL statement")
                continue
            if self.in_string:
                if self.escape:
                    self.token.append(ESCAPES.get(char, char))
                    self.escape = False
                    continue
                if self.pending_quote:
                    self.pending_quote = False
                    if char == "'":
                        self.token.append("'")
                        continue
                    self.in_string = False
                    # Process the delimiter after the closing quote below.
                elif char == "\\":
                    self.escape = True
                    continue
                elif char == "'":
                    self.pending_quote = True
                    continue
                else:
                    self.token.append(char)
                    continue
            if char.isspace() and (self.quoted or not self.token):
                continue
            if char == "'" and self.row is not None and not self.token and not self.quoted:
                self.in_string = self.quoted = True
            elif char == "(" and self.row is None:
                self.row = []
            elif char in ",)" and self.row is not None:
                self.finish_value()
                if char == ")":
                    yield self.row
                    self.row = None
            elif self.row is None and char == ",":
                continue
            elif char == ";" and self.row is None:
                self.done = True
            elif self.row is not None and not self.quoted:
                self.token.append(char)
            else:
                raise ValueError("Unsupported SQL syntax; dump was not executed")


def iter_product_rows(path):
    active = None
    # Streaming skips large unrelated tables without retaining their data.
    with Path(path).open(encoding="utf-8-sig", errors="strict") as source:
        for line_number, line in enumerate(source, 1):
            if active is None:
                if not line.startswith("INSERT INTO `"):
                    continue
                table = line.split("`", 2)[1]
                if table not in TABLES:
                    continue
                match = INSERT.match(line.rstrip("\r\n"))
                if not match:
                    raise ValueError(f"Unsupported INSERT header at line {line_number}")
                columns = re.findall(r"`([^`]+)`", match.group(2))
                active = ValuesParser()
                fragment = match.group(3) + "\n"
            else:
                fragment = line
            try:
                for values in active.feed(fragment):
                    if len(values) != len(columns):
                        raise ValueError("SQL column/value count mismatch")
                    yield table, dict(zip(columns, values))
            except ValueError as error:
                raise ValueError(f"{table} at line {line_number}: {error}") from None
            if active.done:
                active = None
        if active is not None:
            raise ValueError("Truncated product INSERT statement")


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean(value, limit=2000):
    parser = PlainText()
    parser.feed(unescape(str(value or "")))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()[:limit]


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def image_url(value):
    """Preserve an explicit source URL only; do not invent a CDN filename/path."""
    raw = str(value or "").strip()
    try:
        decoded = json.loads(raw)
        raw = decoded[0] if isinstance(decoded, list) and decoded else raw
    except (ValueError, TypeError):
        pass
    if isinstance(raw, str) and raw.startswith("https://") and not any(c.isspace() for c in raw):
        return raw
    return ""


def extract(path, price_field="product_mrp", visibility=("YES",)):
    products, brands, categories = {}, {}, {}
    features = defaultdict(list)
    counts = Counter()
    for table, row in iter_product_rows(path):
        counts[table] += 1
        if table == "les_products":
            pid = row["product_id"]
            if pid in products:
                raise ValueError("Duplicate ID in primary product table")
            products[pid] = row
        elif table == "les_brand":
            brands[row["brand_id"]] = clean(row.get("brand_name"), 150)
        elif table == "les_category":
            categories[row["cat_id"]] = clean(row.get("cat_name"), 150)
        elif table == "les_product_features":
            label, value = clean(row.get("f_name"), 80), clean(row.get("f_value"), 180)
            if label and value:
                features[row["pid"]].append(f"{label}: {value}")
    if not products:
        raise ValueError("No primary les_products rows found")
    skipped = Counter()
    records = []
    for pid, row in products.items():
        if row.get("status") != "Active":
            skipped["not_active"] += 1
            continue
        if row.get("web_display") not in visibility:
            skipped["visibility_not_selected"] += 1
            continue
        name = clean(row.get("product_name"), 300)
        slug = str(row.get("uri_slug") or "").strip()
        link = product_url(slug, pid)
        price = number(row.get(price_field))
        if not name or not link:
            skipped["missing_name_or_valid_url"] += 1
            continue
        if price is None:
            skipped["missing_positive_selected_price"] += 1
            continue
        brand = brands.get(row.get("product_brand"), clean(row.get("product_brand"), 150))
        category = ", ".join(categories.get(c.strip(), c.strip()) for c in
                             str(row.get("cat_id") or "").split(",") if c.strip())
        specs = list(dict.fromkeys(features[pid]))[:20]
        description = clean(row.get("sort_desc") or row.get("product_desc"), 2000)
        # Important facts first: this model truncates long inputs.
        text = " | ".join(filter(None, [name, brand, category, *specs,
                                        clean(row.get("highlights"), 500), description]))[:6000]
        metadata = {
            "product_id": pid, "product_name": name, "brand": brand,
            "category": category, "price": price, "price_field": price_field,
            "sku": clean(row.get("product_sku"), 150), "url": slug,
            "product_url": link, "image_url": image_url(row.get("product_image")),
            "text": text, "features": specs[:8], "status": row["status"],
            "web_display": row["web_display"], "instock": row.get("instock") or "Unknown",
            "source": "sql_snapshot", "source_updated_at": row.get("product_update_date") or "",
            "embedding_model": EMBEDDING_MODEL,
        }
        metadata.update(pricing_metadata(row))
        records.append({"id": pid, "metadata": metadata})
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": Path(path).name, "source_bytes": Path(path).stat().st_size,
        "table_rows": dict(counts), "selected": len(records), "skipped": dict(skipped),
        "price_field": price_field, "price_field_confirmed": False,
        "visibility": list(visibility), "embedding_model": EMBEDDING_MODEL,
        "missing_explicit_image_url": sum(not r["metadata"]["image_url"] for r in records),
        "price_field_positive_counts": {field: sum(number(p.get(field)) is not None
                                                    for p in products.values()) for field in PRICE_FIELDS},
        "notes": ["SQL snapshot is not live inventory.",
                  "Only allowlisted product metadata exported; no customer/order/admin records.",
                  "Confirm selling-price field before upload; no cross-field price fallback.",
                  "Relative image filenames require verified CDN mapping; left blank."],
    }
    return records, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory, preferably under ignored data/product-index/")
    parser.add_argument("--price-field", choices=PRICE_FIELDS, default="product_mrp")
    parser.add_argument("--web-display", nargs="+", default=["YES"],
                        choices=["YES", "ALLOW0STK", "DISPLAY", "ISP", "ESP"])
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output directory already exists; choose a new one")
    records, report = extract(args.sql, args.price_field, args.web_display)
    if not records:
        parser.error("No eligible products; no output written")
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "products.jsonl").open("x", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (args.output_dir / "report.json").open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

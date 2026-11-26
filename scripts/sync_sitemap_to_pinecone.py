"""Incrementally add sitemap-visible Lotus products to the active Pinecone namespace.

The default mode is read-only: it downloads the sitemap and reports IDs missing
from Pinecone.  ``--apply`` fetches those products from the authenticated live
detail API, embeds validated records locally, and upserts them.  It never deletes
vectors or changes ``.env``/the active namespace.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from dotenv import load_dotenv
import requests

from product_index import EMBEDDING_DIMENSION, EMBEDDING_MODEL, IndexSettings, connect_index, product_url
from product_pricing import pricing_metadata


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITEMAP = "https://www.lotuselectronics.com/sitemap.xml"
DETAIL_URL = "https://portal.lotuselectronics.com/web-api/home/product_detail"


def sitemap_products(xml_text):
    """Return {product_id: {url, lastmod}} from a Lotus sitemap."""
    root = ET.fromstring(xml_text)
    products = {}
    for node in root:
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in node}
        url = values.get("loc", "")
        parsed = urlsplit(url)
        match = re.fullmatch(r"/product/(?:[^/]+/)+([1-9]\d*)/?", parsed.path)
        if (parsed.scheme != "https" or parsed.hostname not in
                {"lotuselectronics.com", "www.lotuselectronics.com"} or not match):
            continue
        pid = match.group(1)
        if pid in products and products[pid]["url"] != url:
            raise ValueError(f"Sitemap has conflicting URLs for product {pid}")
        products[pid] = {"url": url, "lastmod": values.get("lastmod", "")}
    if not products:
        raise ValueError("Sitemap contained no valid Lotus product URLs")
    return products


def missing_ids(index, namespace, product_ids, batch_size=500):
    """Fetch IDs in bounded batches and return IDs absent from Pinecone."""
    missing = []
    ordered = sorted(product_ids, key=int)
    for start in range(0, len(ordered), batch_size):
        batch = ordered[start:start + batch_size]
        response = index.fetch(ids=batch, namespace=namespace)
        present = set((getattr(response, "vectors", None) or {}).keys())
        missing.extend(pid for pid in batch if pid not in present)
    return missing


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _image(value):
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = json.loads(value)
            value = parsed[0] if isinstance(parsed, list) and parsed else ""
        except ValueError:
            value = ""
    value = str(value or "").strip()
    return value if value.startswith("https://") else ""


def detail_record(pid, sitemap_entry, detail):
    """Validate a live detail response and produce runtime-compatible metadata."""
    if not isinstance(detail, dict) or str(detail.get("product_id")) != str(pid):
        raise ValueError("Product detail ID mismatch")
    name = _clean(detail.get("product_name"), 300)
    price = detail.get("product_mrp")
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0
    if not name or not math.isfinite(price) or price <= 0:
        raise ValueError("Product name or positive selling price missing")
    canonical = product_url(sitemap_entry["url"], pid)
    if not canonical:
        raise ValueError("Invalid sitemap product URL")
    raw_specs = detail.get("product_specification") or []
    specs = []
    for item in raw_specs if isinstance(raw_specs, list) else []:
        if isinstance(item, dict):
            value = _clean("{}: {}".format(item.get("fkey") or item.get("f_name") or "",
                                           item.get("fvalue") or item.get("f_value") or ""), 260)
            if value != ":":
                specs.append(value)
    specs = list(dict.fromkeys(specs))[:20]
    brand = _clean(detail.get("brand_name") or detail.get("brand"), 150)
    category = _clean(detail.get("cat_name") or detail.get("category_name") or detail.get("category"), 200)
    description = _clean(detail.get("sort_desc") or detail.get("meta_desc"), 1800)
    text = " | ".join(filter(None, [name, brand, category, *specs, description]))[:6000]
    metadata = {
        "product_id": str(pid), "product_name": name, "brand": brand,
        "category": category, "price": price, "price_field": "product_mrp",
        "sku": _clean(detail.get("product_sku"), 150), "url": sitemap_entry["url"],
        "product_url": canonical, "image_url": _image(detail.get("product_image")),
        "text": text, "features": specs[:8], "status": "Active",
        "web_display": "YES", "instock": detail.get("instock") or "Unknown",
        # Keep the active namespace/runtime contract while recording the true
        # delta source separately.
        "source": "sql_snapshot", "sync_source": "website_sitemap",
        "source_updated_at": sitemap_entry.get("lastmod", ""),
        "embedding_model": EMBEDDING_MODEL,
    }
    metadata.update(pricing_metadata(detail))
    return {"id": str(pid), "metadata": metadata}


def fetch_detail(session, token, pid, timeout):
    response = session.post(
        DETAIL_URL,
        headers={"auth-key": "Web2@!9", "auth-token": token, "end-client": "Lotus-Web"},
        data={"product_id": str(pid), "city": "INDORE"},
        timeout=(3, timeout),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or str(payload.get("error", "0")).lower() not in {"0", "false", "none", ""}:
        raise ValueError("Live detail API rejected product")
    data = payload.get("data")
    detail = data.get("product_detail") if isinstance(data, dict) else None
    if not isinstance(detail, dict):
        raise ValueError("Live detail API returned no product")
    return detail


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run(args):
    config = IndexSettings.from_env()
    index, _ = connect_index(config)
    response = requests.get(args.sitemap, timeout=(3, args.timeout))
    response.raise_for_status()
    catalogue = sitemap_products(response.text)
    missing = missing_ids(index, config.namespace, catalogue)
    selected = missing[:args.max_products] if args.max_products else missing
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "namespace": config.namespace, "sitemap_products": len(catalogue),
        "missing_products": len(missing), "selected_products": len(selected),
        "applied": False, "upserted": 0, "skipped": [],
    }
    if not args.apply and not args.prepare_only:
        write_report(args.report, report)
        print(json.dumps(report, indent=2))
        print("Dry run only. Re-run with --apply after reviewing the report.")
        return
    token = os.getenv("LOTUS_AUTH_TOKEN", "").strip()
    if not token:
        raise ValueError("LOTUS_AUTH_TOKEN is required for --apply")
    if not selected:
        report["applied"] = bool(args.apply)
        report["prepared_products"] = 0 if args.prepare_only else None
        write_report(args.report, report)
        print(json.dumps(report, indent=2))
        return
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=args.offline)
    if model.get_sentence_embedding_dimension() != EMBEDDING_DIMENSION:
        raise ValueError("Unexpected embedding model dimension")
    session = requests.Session()
    records = []
    for number, pid in enumerate(selected, 1):
        try:
            detail = fetch_detail(session, token, pid, args.timeout)
            records.append(detail_record(pid, catalogue[pid], detail))
        except (requests.RequestException, ValueError) as error:
            report["skipped"].append({"product_id": pid, "reason": type(error).__name__})
        if args.delay:
            time.sleep(args.delay)
        print(f"Fetched {number}/{len(selected)}", flush=True)
    prepared = []
    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]
        vectors = model.encode([r["metadata"]["text"] for r in batch], batch_size=args.batch_size,
                               normalize_embeddings=True, show_progress_bar=False)
        payload = [{**record, "values": vector.tolist()} for record, vector in zip(batch, vectors)]
        if args.prepare_only:
            prepared.extend(payload)
            continue
        index.upsert(vectors=payload, namespace=config.namespace)
        report["upserted"] += len(payload)
        print(f"Upserted {report['upserted']}/{len(records)}", flush=True)
    if args.prepare_only:
        args.prepare_output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.prepare_output.with_suffix(args.prepare_output.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            for record in prepared:
                output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        temporary.replace(args.prepare_output)
        report["prepared_products"] = len(prepared)
        report["prepare_output"] = str(args.prepare_output)
    report["applied"] = bool(args.apply)
    write_report(args.report, report)
    print(json.dumps(report, indent=2))


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sitemap", default=DEFAULT_SITEMAP)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/product-index/sitemap-sync.json")
    parser.add_argument("--apply", action="store_true", help="Explicitly upsert missing products")
    parser.add_argument("--prepare-only", action="store_true",
                        help="Fetch and embed locally without any Pinecone upsert")
    parser.add_argument("--prepare-output", type=Path,
                        default=ROOT / "artifacts/product-index/sitemap-vectors.jsonl")
    parser.add_argument("--offline", action="store_true", help="Use only the locally cached embedding model")
    parser.add_argument("--max-products", type=int, default=0, help="Limit this run; 0 means all missing products")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--delay", type=float, default=0.05, help="Delay between detail requests")
    args = parser.parse_args()
    if args.apply and args.prepare_only:
        parser.error("Choose either --apply or --prepare-only")
    if not 1 <= args.batch_size <= 64 or args.max_products < 0 or not 1 <= args.timeout <= 60 or not 0 <= args.delay <= 5:
        parser.error("Invalid batch-size, max-products, timeout, or delay")
    try:
        run(args)
    except ValueError as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Sync failed ({type(error).__name__}); no credentials were printed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

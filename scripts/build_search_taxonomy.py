"""Build search vocabulary from a validated export; never contacts/writes Pinecone."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--categories-sql", type=Path, help="Read only les_category hierarchy; never execute SQL")
    parser.add_argument("--output", type=Path, default=Path("smart_search_taxonomy.json"))
    args = parser.parse_args()
    rows = [json.loads(line)["metadata"] for line in args.products.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        parser.error("The validated export is empty")
    invalid_brands = {"0", "No Brand", "Ram", "Camera", "General", ""}
    vocabulary = {
        "namespace": args.namespace,
        "version": hashlib.sha256(args.products.read_bytes()).hexdigest(),
        "brands": sorted({r.get("brand", "") for r in rows} - invalid_brands),
        "categories": sorted({r.get("category", "") for r in rows} - {"0", ""}),
    }
    vocabulary["brandCategories"] = {
        brand: sorted({r.get("category", "") for r in rows if r.get("brand") == brand} - {"0", ""})
        for brand in vocabulary["brands"]
    }
    if args.categories_sql:
        from scripts.extract_products import iter_product_rows, clean
        vocabulary["categoryTree"] = [
            {"id": str(row["cat_id"]), "name": clean(row["cat_name"], 150),
             "parentId": str(row.get("cat_parent_id") or "0"), "active": row.get("is_active") == "1"}
            for _, row in iter_product_rows(args.categories_sql, allowed_tables={"les_category"})
        ]
    vocabulary["version"] = hashlib.sha256(json.dumps(vocabulary, sort_keys=True).encode()).hexdigest()
    args.output.write_text(json.dumps(vocabulary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(vocabulary['brands'])} brands and {len(vocabulary['categories'])} categories to {args.output}")


if __name__ == "__main__":
    main()

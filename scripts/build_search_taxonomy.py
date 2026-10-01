"""Build search vocabulary from a validated export; never contacts/writes Pinecone."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
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
    vocabulary["version"] = hashlib.sha256(json.dumps(vocabulary, sort_keys=True).encode()).hexdigest()
    args.output.write_text(json.dumps(vocabulary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(vocabulary['brands'])} brands and {len(vocabulary['categories'])} categories to {args.output}")


if __name__ == "__main__":
    main()

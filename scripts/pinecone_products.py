"""Check, embed, and explicitly upload extracted products. No index creation/deletion.

Commands are separate: `check` is read-only, `embed` writes local vectors only,
and `upload` requires a confirmed price field and a named empty namespace.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from product_index import EMBEDDING_DIMENSION, EMBEDDING_MODEL, IndexSettings, connect_index
from scripts.extract_products import PRICE_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def load_records(path, vectors=False):
    records, ids = [], set()
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            record = json.loads(line)
            pid, metadata = record.get("id"), record.get("metadata", {})
            if not isinstance(pid, str) or not pid or pid in ids:
                raise ValueError("Missing/duplicate product ID")
            if metadata.get("product_id") != pid or metadata.get("source") != "sql_snapshot":
                raise ValueError("Only validated SQL product exports can be uploaded")
            if metadata.get("embedding_model") != EMBEDDING_MODEL:
                raise ValueError("Embedding model mismatch")
            if not metadata.get("text") or not metadata.get("product_url"):
                raise ValueError("Product text or URL missing")
            price = metadata.get("price")
            if not isinstance(price, (float, int)) or not math.isfinite(price) or price <= 0:
                raise ValueError("Invalid product price")
            if len(json.dumps(metadata).encode()) > 35000:
                raise ValueError("Product metadata too large")
            if vectors:
                values = record.get("values", [])
                if len(values) != EMBEDDING_DIMENSION or not all(
                    isinstance(v, (float, int)) and math.isfinite(v) for v in values
                ):
                    raise ValueError("Invalid vector dimensions or non-finite values")
            records.append(record)
            ids.add(pid)
    if not records:
        raise ValueError("No products in input file")
    return records


def settings(namespace=None):
    # Namespace override is scoped to this command, never written into .env.
    previous = os.environ.get("PINECONE_NAMESPACE")
    if namespace:
        os.environ["PINECONE_NAMESPACE"] = namespace
    try:
        return IndexSettings.from_env()
    finally:
        if previous is None:
            os.environ.pop("PINECONE_NAMESPACE", None)
        else:
            os.environ["PINECONE_NAMESPACE"] = previous


def inspect_index(config):
    from pinecone import Pinecone
    client = Pinecone(api_key=config.api_key, timeout=15)
    indexes = list(client.list_indexes())
    matching = [i for i in indexes if i.host.removeprefix("https://").rstrip("/") == config.host.removeprefix("https://")]
    if not matching:
        raise ValueError("Configured host was not found in the key's project. Check project/key/host.")
    description = matching[0]
    if description.name != config.name:
        # No API keys, response headers, or request payloads in error messages.
        raise ValueError(f"Index name mismatch: configured={config.name}; host belongs to={description.name}")
    return connect_index(config)


def embed(input_path, output_path, batch_size, offline=False):
    if output_path.exists():
        raise ValueError("Vector output exists; choose a new path")
    records = load_records(input_path)
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBEDDING_MODEL, local_files_only=offline)
    if model.get_sentence_embedding_dimension() != EMBEDDING_DIMENSION:
        raise ValueError("Unexpected model dimensions")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # A .partial file is not accepted as the completed output. Failed jobs never
    # replace an existing vector file and are not uploaded automatically.
    partial = output_path.with_suffix(output_path.suffix + ".partial")
    with partial.open("x", encoding="utf-8") as target:
        for start in range(0, len(records), batch_size):
            batch = records[start:start + batch_size]
            vectors = model.encode([r["metadata"]["text"] for r in batch],
                                   batch_size=batch_size, normalize_embeddings=True,
                                   show_progress_bar=False)
            for record, vector in zip(batch, vectors):
                record["values"] = vector.tolist()
                target.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            print(f"Embedded {min(start + batch_size, len(records))}/{len(records)}", flush=True)
    partial.rename(output_path)
    print(f"Local vectors ready: {output_path}. Nothing uploaded.")


def validate_upload(records, confirmed_price_field):
    fields = {r["metadata"].get("price_field") for r in records}
    if fields != {confirmed_price_field}:
        raise ValueError("Confirmed price field does not match extracted data")


def upload(args):
    if args.input.suffix != ".jsonl":
        raise ValueError("Only completed .jsonl vector files can be uploaded, not .partial files")
    records = load_records(args.input, vectors=True)
    validate_upload(records, args.confirm_price_field)
    config = settings(args.namespace)
    if config.namespace in {"", "__default__"}:
        raise ValueError("Use a new named namespace to isolate this SQL import")
    index, stats = inspect_index(config)
    namespace = stats.namespaces.get(config.namespace)
    if namespace and namespace.vector_count and not args.resume:
        raise ValueError("Namespace is not empty. Choose a new one; --resume is only for this same import")
    # A local receipt pins retries to the same index, namespace, and exact file.
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    receipt_path = args.input.with_suffix(".upload.json")
    identity = {"host": config.host, "namespace": config.namespace, "sha256": digest}
    if args.resume:
        if not receipt_path.exists():
            raise ValueError("No upload receipt; cannot safely resume")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if any(receipt.get(k) != v for k, v in identity.items()):
            raise ValueError("Resume target/input mismatch")
    else:
        receipt = {**identity, "count": len(records), "price_field": args.confirm_price_field,
                   "completed": False}
        with receipt_path.open("x", encoding="utf-8") as target:
            json.dump(receipt, target, indent=2)
    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]
        # Small batches remain under Pinecone's request size limits.
        index.upsert(vectors=batch, namespace=config.namespace)
        print(f"Uploaded {min(start + args.batch_size, len(records))}/{len(records)}", flush=True)
    receipt["completed"] = True
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print("Upload completed. Wait for indexing, then verify count and search before activating namespace.")


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="Read-only index configuration and vector counts")
    check.add_argument("--namespace", default="lotus-products-sql")
    local = sub.add_parser("embed", help="Create local vectors only")
    local.add_argument("--input", type=Path, required=True)
    local.add_argument("--output", type=Path, required=True)
    local.add_argument("--batch-size", type=int, default=32)
    local.add_argument("--offline", action="store_true", help="Use the downloaded model cache only")
    push = sub.add_parser("upload", help="Explicitly upsert validated vectors")
    push.add_argument("--input", type=Path, required=True)
    push.add_argument("--namespace", required=True)
    push.add_argument("--confirm-price-field", choices=PRICE_FIELDS, required=True)
    push.add_argument("--batch-size", type=int, default=32)
    push.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if hasattr(args, "batch_size") and not 1 <= args.batch_size <= 64:
        parser.error("batch-size must be between 1 and 64")
    try:
        if args.command == "check":
            config = settings(args.namespace)
            _, stats = inspect_index(config)
            print(json.dumps({"name": config.name, "dimension": stats.dimension,
                              "total_vector_count": stats.total_vector_count,
                              "namespaces": {k: v.vector_count for k, v in stats.namespaces.items()}}, indent=2))
        elif args.command == "embed":
            embed(args.input, args.output, args.batch_size, args.offline)
        else:
            upload(args)
    except ValueError as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # SDK exceptions can include headers or credentials. Never dump them.
        print(f"Operation failed ({type(error).__name__}). Check credentials, network, "
              "dependencies and index access. No keys printed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Plan/apply additive pricing metadata for existing SQL product vectors only.

No embeddings, vectors, selected filter price, product content or records are replaced.
The saved plan records the prior metadata and exact target before any update.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import time

from dotenv import load_dotenv
from product_index import IndexSettings, connect_index
from product_pricing import pricing_metadata
from scripts.extract_products import iter_product_rows


def fetch_metadata(index, ids, namespace):
    result = {}
    for start in range(0, len(ids), 500):
        response = index.fetch(ids=ids[start:start + 500], namespace=namespace)
        result.update({pid: dict(value.metadata or {}) for pid, value in response.vectors.items()})
    if set(result) != set(ids):
        raise ValueError('Pinecone IDs do not match the saved SQL import; nothing updated.')
    return result


def validate_additions(current, original, additions):
    if any(current.get(key) != value for key, value in original.items()):
        raise ValueError('Original product metadata changed; refusing to update this plan.')
    if any(key in current and current[key] != value for key, value in additions.items()):
        raise ValueError('Conflicting existing price metadata; refusing to overwrite it.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--sql', type=Path)
    parser.add_argument('--products', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    settings = IndexSettings.from_env()
    index, stats = connect_index(settings)
    target = {'index': settings.name, 'host': settings.host, 'namespace': settings.namespace}

    if not args.apply:
        if not args.sql or not args.products or args.plan.exists():
            raise ValueError('Planning requires SQL/products paths and a new plan file.')
        exported = [json.loads(line) for line in args.products.read_text(encoding='utf-8').splitlines() if line]
        original = {row['id']: row['metadata'] for row in exported}
        if len(original) != len(exported):
            raise ValueError('Duplicate product IDs in the export.')
        sources = {}
        for table, row in iter_product_rows(args.sql):
            if table == 'les_products' and row.get('product_id') in original:
                sources[row['product_id']] = {key: row.get(key) for key in (
                    'product_msrp', 'product_mrp', 'wprice2', 'eff_price')}
        if set(sources) != set(original):
            raise ValueError('SQL source does not contain every imported product.')
        if stats.namespaces[settings.namespace].vector_count != len(original):
            raise ValueError('Namespace count differs from saved import; nothing updated.')
        current = fetch_metadata(index, list(original), settings.namespace)
        entries = []
        for pid, old in original.items():
            additions = pricing_metadata(sources[pid])
            if old.get('price_field') != 'product_mrp' or additions.get('product_mrp') != old.get('price'):
                raise ValueError('Selected snapshot price does not match this SQL source.')
            validate_additions(current[pid], old, additions)
            entries.append({'id': pid, 'before': current[pid], 'source_prices': sources[pid], 'add': additions})
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        with args.plan.open('x', encoding='utf-8') as file:
            json.dump({'target': target, 'entries': entries}, file, ensure_ascii=False)
        print(f'Plan saved: {len(entries)} existing products; no Pinecone writes.', flush=True)
        print(f'Products with a list MRP and selling price: {sum("mrp" in e["add"] and "selling_price" in e["add"] for e in entries)}', flush=True)
        return

    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if plan['target'] != target:
        raise ValueError('Configured index/host/namespace differs from the reviewed plan.')
    entries = plan['entries']
    ids = [entry['id'] for entry in entries]
    if len(set(ids)) != len(ids) or stats.namespaces[settings.namespace].vector_count != len(ids):
        raise ValueError('Duplicate IDs or changed namespace count.')
    current = fetch_metadata(index, ids, settings.namespace)
    pending = []
    for entry in entries:
        if entry['add'] != pricing_metadata(entry['source_prices']):
            raise ValueError('Plan pricing calculation is inconsistent.')
        validate_additions(current[entry['id']], entry['before'], entry['add'])
        if any(current[entry['id']].get(k) != v for k, v in entry['add'].items()):
            pending.append(entry)

    def update(entry):
        for attempt in range(3):
            try:
                index.update(id=entry['id'], namespace=settings.namespace, set_metadata=entry['add'])
                return entry['id']
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)

    completed, failures = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(update, entry): entry['id'] for entry in pending}
        for future in as_completed(futures):
            try:
                completed.append(future.result())
            except Exception as exc:
                failures.append({'id': futures[future], 'error_type': type(exc).__name__})
            if (len(completed) + len(failures)) % 250 == 0:
                print(f'Pricing metadata updated: {len(completed)}/{len(pending)}; failures: {len(failures)}', flush=True)
    receipt = {'target': target, 'updated': len(completed), 'already_current': len(entries) - len(pending), 'failures': failures}
    args.plan.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    if failures:
        raise RuntimeError('Some updates failed; saved plan can be safely retried.')
    for attempt in range(5):
        verified = fetch_metadata(index, ids, settings.namespace)
        if all(all(verified[e['id']].get(k) == v for k, v in e['add'].items()) for e in entries):
            for entry in entries:
                validate_additions(verified[entry['id']], entry['before'], entry['add'])
            receipt['verified'] = len(entries)
            args.plan.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
            print(f'Verified all {len(entries)} products and original metadata. Only pricing metadata was updated; vectors were not rewritten.', flush=True)
            return
        time.sleep(2)
    raise RuntimeError('Updates accepted; verification has not converged yet. Rerun the same plan.')


if __name__ == '__main__':
    main()

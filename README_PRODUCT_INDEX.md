# SQL products to Pinecone (MiniLM, bring your own vectors)

The importer never executes SQL. It reads only `les_products`, `les_brand`,
`les_category` and `les_product_features`, not backups or customer/order tables.
Only allowlisted public product fields are exported. Keep dumps and generated
files private; `data/product-index/` is ignored by Git.

## Configuration

Use a **dense, bring-your-own-vectors, 384-dimensional, cosine** Pinecone index.
Do not use an integrated `llama-text-embed-v2` index: equal dimensions do not make
different models compatible. The scripts validate the index before uploading.
Create a compatible index in the company account; the importer commands do not
create or delete indexes. Never paste API keys into chat or source code.

Current setup: `lotus-products-minilm` was created as a separate serverless index
in AWS `us-east-1`, with deletion protection enabled. The existing integrated
`all-lotus-product` index was preserved. `.env` selects the new index.

On 2026-09-28, 3,474 product vectors were uploaded and the same count was verified
in namespace `lotus-products-sql-20260928`. The local upload receipt is
`data/product-index/sql-preview/vectors.upload.json`. No customer/order records
were uploaded. `product_mrp` is the selected online selling price from the snapshot,
not a live-price guarantee. Lotus's list MRP is `product_msrp`.

Verification on that date: the restarted local app reported Pinecone connected;
`POST /search` returned real smartphones within the requested budget, and one
returned storefront product URL responded HTTP 200. An end-to-end chat test
successfully called `recommend_products`, but the subsequent Gemini response
failed with `429 RESOURCE_EXHAUSTED` (daily model request quota). Pinecone product
retrieval is operational; full chat completion still depends on available Gemini quota.

Add to the existing `.env` without replacing its other settings:

```dotenv
ENABLE_VECTOR_SEARCH=true
PINECONE_API_KEY=<your-project-key>
PINECONE_INDEX_NAME=<your-new-index-name>
PINECONE_HOST=<your-new-index-host>
PINECONE_NAMESPACE=lotus-products-sql-20260928
```

Index name and host must describe the same index. Namespace is explicit on both
upload and search. Policy search is separate, gated by
`ENABLE_POLICY_VECTOR_SEARCH`; enabling products does not enable the old policy
index. Restart the app only after upload and validation to activate this config.

## 1. Extract and review (no network)

From the project directory, PowerShell:

```powershell
.\.venv\Scripts\python.exe -m scripts.extract_products --sql "C:\Users\mayur\Downloads\lotuselectronics_db15.sql" --output-dir data/product-index/sql-preview --price-field product_mrp
```

The directory must be new. The current import uses `product_mrp` as the selected
online selling price. On 2026-09-29, the official product page and its display code
confirmed this mapping: `product_msrp` is list MRP, `product_mrp` is online selling
price, and `eff_price` is a conditional **in-store offer**. `wprice2` is retained as
a raw source field; it is not silently used as the online price.

The extractor now retains all four source price fields and adds `mrp`,
`selling_price`, `store_offer_price`, `discount_amount`, and `discount_percent`.
Discount is calculated from list MRP minus online selling price. A missing MRP
never becomes an invented discount. Search budget filters continue using the
selected `price` field. Snapshot prices can differ from current store prices.

Existing vectors can receive additive price metadata without re-embedding:

```powershell
.\.venv\Scripts\python.exe -m scripts.backfill_product_prices --plan data/product-index/sql-preview/pricing-backfill-20260929.json --sql "C:\Users\mayur\Downloads\lotuselectronics_db15.sql" --products data/product-index/sql-preview/products.jsonl
.\.venv\Scripts\python.exe -m scripts.backfill_product_prices --plan data/product-index/sql-preview/pricing-backfill-20260929.json --apply
```

Planning saves the original metadata and exact target; it does not write to
Pinecone. Apply verifies every original product, adds only the reviewed price
fields, leaves vector values and existing search prices untouched, and verifies
all records afterward. The receipt is saved beside the plan. The original vector
export remains an archive: do not re-upload it over enriched records, as its old
metadata lacks these fields. New exports use the corrected extractor.

Review `report.json` and `products.jsonl`. Default selection is `status=Active`
and `web_display=YES`, a conservative subset. Additional visibility values need
business confirmation and can be passed using `--web-display YES ALLOW0STK` etc.
Invalid/missing names, slugs and nonpositive prices are skipped and counted.
Explicit image URLs are preserved. Relative filenames are left blank until a
real CDN mapping is verified. URLs derive from `uri_slug` and `product_id`.

## 2. Generate local embeddings (no Pinecone writes)

```powershell
.\.venv\Scripts\python.exe -m scripts.pinecone_products embed --input data/product-index/sql-preview/products.jsonl --output data/product-index/sql-preview/vectors.jsonl --offline
```

`--offline` uses an already downloaded Hugging Face model. On a new machine,
omit that flag once to download `sentence-transformers/all-MiniLM-L6-v2` (requires
network access); product text is embedded locally, not sent to Hugging Face.
The importer and runtime use normalized vectors from that same model.
Runtime uses the cached model only. Existing vector files are never overwritten;
failed builds leave a `.partial` file and cannot be uploaded as complete output.

## 3. Read-only connection check

```powershell
.\.venv\Scripts\python.exe -m scripts.pinecone_products check --namespace lotus-products-sql-20260928
```

This checks the project/index/host, dimension, metric, model type and vector counts.
It does not modify the index. The key needs index read/describe permissions in
addition to query/fetch permissions; upload also needs upsert permission.

## 4. Explicit upload, only after price confirmation

```powershell
.\.venv\Scripts\python.exe -m scripts.pinecone_products upload --input data/product-index/sql-preview/vectors.jsonl --namespace lotus-products-sql-20260928 --confirm-price-field product_mrp
```

This uploads product embeddings and allowlisted metadata to your Pinecone account
and may incur usage charges. Use a fresh named namespace. By default an existing
nonempty namespace is rejected. An interrupted upload can be retried using
`--resume` with the exact same input and target, verified against its local receipt.
No records or indexes are deleted. Use a new namespace for subsequent snapshots
so products removed from the SQL export do not remain in the active search set.

## 5. Verify and activate

Wait for Pinecone indexing, run the check again, and verify the namespace count
matches the report. Restart the local app, check `/health`, then test `/search`
with a real product query. Confirm prices, features and destination links against
the storefront before deployment. Do not claim snapshot stock/prices are live.

Search, recommendations and category browsing now use this index with explicit
unavailable errors, not a demo fallback. Other legacy flows (orders/comparisons/
detail fallback) still contain catalog/demo code and need a separate migration
before treating the entire chatbot as a production commerce backend.

Tests (no model/API calls):

```powershell
.\.venv\Scripts\python.exe -m unittest test_product_index -v
```

## Optional live price and stock verification

Phase 1 keeps the existing SQL vectors, IDs, embeddings, namespace, and search
ranking. It adds read-only verification against the already configured
`POST https://portal.lotuselectronics.com/web-api/home/product_detail` API.
No Pinecone upsert, metadata update, deletion, or re-embedding is performed.

Backend settings (keep the existing `LOTUS_AUTH_TOKEN` secret in `.env`):

```dotenv
LOTUS_LIVE_ENRICHMENT=true
LOTUS_LIVE_ENRICHMENT_TIMEOUT=6
```

The flag defaults to false when absent. Restart the backend after changing `.env`.
Set the flag to false and restart to restore the existing snapshot search path.
The six-second verification deadline is separate from Pinecone/embedding time.
An invalid deadline uses the six-second default; allowed values are >0 and <=30.
Existing per-call HTTP timeouts remain `(3, 8)` seconds. Late requests cannot
update a response that has already been returned. The shared pool has eight
workers and at most 24 outstanding calls per process, including timed-out calls.

Search, browsing, recommendations, and comparison accept a `city` (default
`INDORE`, matching the existing details tool). Example using the existing route:

```http
POST /search
Content-Type: application/json

{"query":"Samsung double door refrigerator","top_k":3,"price_max":40000,"city":"INDORE"}
```

The response envelope and product-card fields remain compatible. Additional fields
on each verified card include `price_verified`, `price_source`, `stock_verified`,
`stock_city`, and `checked_at`. `data.live_verification` reports candidate counts,
unverified counts, completeness, and `scope: retrieved_candidates_only`.

With live mode enabled, retrieval does not prefilter by the old snapshot price:
a product discounted from 36,999 to 34,999 must not be excluded before a 35,000
budget check. Up to 20 semantic candidates are retrieved as before; the first
`min(20, max(top_k, 10))` intent-matching candidates are verified in parallel.
Only current verified selling prices are used for minimum/maximum budget filters.
This is bounded candidate search, not exhaustive catalogue coverage. Price
boundaries remain inclusive, matching the existing endpoint convention.

Product ID must match exactly. If both records have a SKU, that must match too.
Location must match the requested city. Live selling price, MRP, discounts and
store offers are not mixed with old snapshot pricing fields. Conditional store
offers never become the online selling price. Price and stock are checked on
each request; no price/stock cache has been introduced.

On API failure, search returns real Pinecone catalogue names, images, links and
features, with a last-known catalogue price when present. These cards carry
`catalogue_fallback: true`, `catalogue_price` and `price_verified: false`; their
stock remains `Unknown` unless that stock was independently verified. Catalogue
prices can suggest budget options during an outage, but never guarantee a current
budget match. Successfully verified live prices always override catalogue prices.
If the normal verification batch finds no budget options during an outage, the
remaining already-retrieved Pinecone candidates can supply catalogue options
without extra API requests. If neither live nor catalogue candidates match the
budget, the existing `price_unverified` error remains. An actual API `instock: No`
remains out of stock; an API failure never means that.

The chat preserves fallback cards even when the model replies with only an
apology. It shows a dismissible "Verify live price & stock" popup, a last-known
price label and the real View product link. The popup is driven by current-turn
backend fallback facts; successful live responses do not show it. In-stock-only
recommendations return unconfirmed alternatives separately as `catalogue_products`,
so these are never asserted to be confirmed in stock. Orders still require their
existing independent successful live price/stock check.

In-stock recommendations reuse the already verified results instead of making a
second batch of API calls. Orders still perform their existing independent stock
and price recheck and remain local demo orders. In live mode comparisons resolve
live/indexed details before any demo data. Current-turn tool product cards are
preserved in the final chat response before logging, so the model cannot replace
their structured prices with older conversation values. Old cards without a
current-turn verification do not retain verified price/stock claims. The existing
chat graph and conversation persistence flow remain in place; a feature-gated
instruction tells the model to use current tool facts for price/stock prose.

New-product ingestion is a separate phase, not enabled here. A new API product
that is absent from Pinecone will not automatically become searchable. The
category API must first be verified for complete pagination, visibility rules,
stable IDs, and its observed sorting/page error before building an incremental
importer. Do not import only the first ten returned products or delete catalogue
records on the basis of a failed/partial API read.

Offline regression checks (no provider calls; the suite uses temporary databases):

```powershell
.\.venv\Scripts\python.exe -m unittest test_live_enrichment test_chat_turns test_product_index test_product_pricing test_product_availability test_bulk_orders -q
```

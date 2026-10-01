# Website smart search

`POST /api/search/smart` is a separate, stateless website endpoint. Existing
`/chat`, `/search`, prompts, history and tool execution remain unchanged.
It reuses the existing Pinecone client, MiniLM embedding model, unbound Gemini
client/configuration, price mapping and live product-detail verification.
There are no vector writes, new providers, generated products or generated SQL.

## Request

```http
POST http://127.0.0.1:8001/api/search/smart
Content-Type: application/json

{
  "query": "Samsung ka double door fridge 40 hazar ke andar",
  "page": 1,
  "pageSize": 24,
  "city": "INDORE",
  "category": "Refrigerator"
}
```

Fields: query 2–300 characters; page integer 1–200; pageSize integer 1–48
(default 24); city 1–100 characters (default INDORE); optional brandMatch is
`family` (default, allow validated catalogue-name resolution) or `exact`. Unsupported fields are
rejected rather than silently ignored. Responses follow `{status, data}`.
Optional `category` defaults to `all` (normal search). An exact catalogue label
such as `Double Door Refrigerator` or a supported broad alias such as
`Refrigerator`, `laptop`, `tv`, `ac`, `washing machine`, or `phone` constrains
retrieval to that category/group. Brand matching runs within that scope.
Unknown categories or conflicting query categories return HTTP 400. The LLM
cannot broaden the selected category. `data.selectedCategory` echoes the choice.
Product cards are in `data.products` and include existing `product_id`,
`product_name`, `product_mrp` (formatted online price), `selling_price`,
`product_url`, `product_image`, features, and verified availability fields.
This endpoint also includes `brand`, `category`, and `sku`.

Complete captured HTTP request/response examples (real catalogue data, not mocks):

- [Hinglish query, three products](artifacts/smart-search/hinglish.json)
- [Default pageSize 24](artifacts/smart-search/default-page.json)
- [Voltas typo query, valid zero matches](artifacts/smart-search/typo.json)
- [AI-assisted 5-star specification query](artifacts/smart-search/attribute.json)

These files are test-time snapshots, not current price guarantees. Each new
endpoint request verifies prices again.

`data.interpretedQuery` describes normalized constraints and ranking preferences;
`appliedFilters` excludes ranking preferences. `corrections` records replacements
such as `voltus → voltas`, `refregistor → refrigerator`, and `fridge → refrigerator`.
Unrelated brands are never substituted. An LLM may resolve a shortened brand
to its actual compound catalogue name when the requested category exists under
that name. `brandResolution` preserves requested and applied brands;
`searchNotices` discloses the mapping. `brandMatch: "exact"` and only/sirf wording
prevent it. Explicit compound names remain specific.
A valid zero-match response has HTTP 200 and an empty products array.

## Retrieval and pagination contract

Known brand/category filters apply inside Pinecone. Model and literal attribute
constraints are also checked against catalogue names/SKUs/features. Exact SKU
lookup receives priority. Supported category labels can constrain use cases
(e.g. Gaming Laptop); other use cases only influence ranking. Unrecognized
specifications are matched literally, so coverage is conservative. This version
does not promise every spelling variation or synonym will match.

Pinecone returns a maximum ranked window of 200 candidates. Pages partition
that window AFTER brand/category/specification filtering and BEFORE live budget
filtering. A page can be short or empty when its candidates exceed the budget.
Snapshot prices are used only to rank likely budget matches earlier; they never
exclude candidates or become displayed prices.
Use `pagination.nextPage` / `hasMoreCandidates`, not products.length, to continue.
`pagination.total` is null: it is not a whole-catalogue match count.
`windowMayBeTruncated` warns when the retrieval limit is reached.
Ordering can change when the index changes between requests; there is no frozen
search-session cache or cursor. This is bounded website discovery, not a full
catalogue export or guaranteed exhaustive SQL-style pagination.

Live verification runs in batches of at most 20 using the existing bounded
worker pool and deadline. Prices/inventory are never cached here. Every explicit
budget is checked against verified current online prices, never snapshot prices
or conditional store offers. Missing price/stock is marked unknown. Partial
verification is reported in `data.verification`; do not treat an unverified
price as zero or unknown stock as out of stock.

## AI and failures

Every valid, uncached query goes to the existing Gemini client FIRST, including
simple queries such as `mobile under 35000` and `voltas washing machine`.
The complete original query, real catalogue vocabulary and indexed brand-category
pairs go into a separate structured-output prompt. Lexical parsing supplies
constraint checks and a failure fallback; it does not bypass the LLM or override
a validated semantic interpretation. Calls
contain only a system prompt and the current query; there are no chat messages,
tools, conversation history or actions. The AI returns source phrases and typed
resolutions for every unresolved term. Valid category synonyms are consumed as
category mappings, not reapplied as literal title requirements. `smart phone`
can therefore match Android Smartphone without requiring the word `smart`.
Hinglish descriptions such as `kapde dhone ki machine` can map to washing-machine
categories; use cases such as `good camera` become ranking preferences, not
invented megapixel constraints. Retrieval embeds the canonical interpreted intent.

Grounding checks reject missing source phrases, omitted constraints, unsupported
labels, unrelated brand substitutions, changed numeric specifications and colours,
or modified known budgets. Brand typo corrections require a unique close match
to the catalogue. Ambiguous or unsupported mappings fall back conservatively;
this is not a guarantee that every arbitrary phrase will be understood.

`data.interpretationSource` is `ai`, `ai_cache`, or `keyword`. There is no normal
deterministic-only route. The existing `searchMode` contract is unchanged.

Brand selection comes from the LLM using actual indexed brand-category pairs,
not a per-brand rewrite table. The generic validator allows a more specific
compound label only when it preserves the complete requested name and is present
in the relevant catalogue category. For example, the LLM can select Voltas Beko
for a Voltas washing-machine request while keeping Voltas for ACs. Broader
unrelated brand associations remain unsupported rather than silently guessed.

Gemini receives an inlined native JSON schema with structural types, required
fields and enums. Array/string length and numeric limits are enforced by the
full strict Pydantic schema after generation. This avoids the HTTP 400 rejection
observed with the original nested bounded schema on the configured model.
See [Gemini structured-output documentation](https://ai.google.dev/gemini-api/docs/structured-output)
for provider schema limitations; application validation remains authoritative.

On timeout, capacity saturation, provider failure or invalid output, response
metadata contains `searchMode: "keyword"` and `fallbackReason` of `ai_timeout`,
`ai_busy`, `ai_provider_failure`, or `invalid_ai_output`. The fallback reuses the
existing Pinecone/embedding infrastructure with deterministic filters and strict
literal term checks. The project has no separate full-text catalogue service;
this fallback is not an exhaustive database keyword scan.

Catalogue failures and an inability to verify any candidate prices return:

```json
{
  "status": "error",
  "error": "Current product prices unavailable; try again later",
  "error_code": "smart_search_unavailable"
}
```

HTTP 503 is distinct from a successful empty array. Invalid input returns 400;
request bodies over 8 KiB return 413. Unexpected internal errors are logged and
return a generic 503 without secrets. Successful responses use Cache-Control:
no-store.

## Configuration and deployment

Existing backend settings remain required: `ENABLE_VECTOR_SEARCH=true`,
`PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_HOST`, `PINECONE_NAMESPACE`,
existing cached MiniLM model, `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), existing
`GEMINI_MODEL`, and `LOTUS_AUTH_TOKEN` for live product details. Do not put these
credentials in Angular.

- `SMART_SEARCH_AI_TIMEOUT=12`: optional interpretation deadline in seconds,
  positive and at most 15; invalid values use 12. Outstanding AI calls are bounded
  to four per process; timed-out running SDK calls hold a slot until they finish.
  Each search request also passes the deadline and a single HTTP attempt to the
  shared client's invocation, preventing chatbot retries from extending search
  work in the background. Chatbot client defaults are not modified.
  Gemini rejects a manually supplied HTTP deadline below ten seconds. For
  configured limits under ten, the caller still falls back at its requested
  deadline while the provider call has a ten-second minimum and retains its
  bounded slot until completion. The default twelve seconds satisfies both.
- `LOTUS_LIVE_ENRICHMENT_TIMEOUT=6`: existing per-batch live verification deadline.
  Smart search always verifies live prices, independently of the chatbot's
  `LOTUS_LIVE_ENRICHMENT` flag. Larger pages can need multiple batches.
- `SMART_SEARCH_TAXONOMY_PATH`: optional path to vocabulary JSON; default is
  `smart_search_taxonomy.json` beside the backend module. Its namespace must
  match the active index namespace or search returns 503.

The committed vocabulary was derived from the current validated product export;
it contains labels/version context only, no price or inventory. Successful,
validated AI interpretations are cached per process for five minutes (maximum
256 entries), keyed by normalized original query, brand mode, namespace and vocabulary version.
Failures, products, price and stock are never cached. The shared AI client and
prompt configuration are fixed for the lifetime of a process; restart after
changing them. After catalogue reindexing/new brands or categories, regenerate
and deploy the vocabulary with the matching index, then restart the service:

```powershell
.venv/Scripts/python.exe scripts/build_search_taxonomy.py --products data/product-index/sql-preview/products.jsonl --namespace lotus-products-sql-20260928 --output smart_search_taxonomy.json
```

New products become searchable once the existing indexing pipeline adds them to
Pinecone. This endpoint does not add an ingestion scheduler; API-only products
that have not been indexed cannot be discovered here. Price changes do not need
re-embedding because displayed prices are fetched live.

Authentication matches existing public `/search` and `/chat`: no new login
requirement. The existing nginx `/api/` location supplies rate limiting at 10
requests/second per IP with burst 20. Use that proxy in deployment; the raw Flask
development port is not rate limited. No frontend or nginx changes are included.

## Angular integration

Use your same-origin backend proxy (or configure the deployment's allowed CORS
origin) and keep the existing product-card component:

```typescript
this.http.post<any>('/api/search/smart', {
  query: this.searchText, category: this.selectedCategory || 'all', page: 1, pageSize: 24, city: 'INDORE'
}).subscribe({
  next: response => {
    this.products = response.data.products;
    this.nextPage = response.data.pagination.nextPage;
    // Show corrections/fallback metadata and unknown prices when present.
  },
  error: () => { /* Show retry state; do not display "no products found". */ }
});
```

Use debounceTime/distinctUntilChanged/switchMap for a search-as-you-type UI.
Append subsequent pages with the same query/category/pageSize/city; deduplicate by
product_id if the catalogue is being updated. The backend already returns an
array; Angular does not need to parse chatbot text.

## Verification

```powershell
.venv/Scripts/python.exe -m unittest test_smart_search test_live_enrichment test_chat_turns test_product_index test_product_pricing test_product_availability test_bulk_orders -q
```

The focused tests cover amount normalization, typo/brand/category constraints,
budget boundaries, current-price filtering, invalid output, timeout/provider
fallbacks, outage errors, request validation, SKU priority, pagination, no chat
imports/history/tools and unchanged existing chatbot regression checks.

On 2026-09-30, 122 offline tests passed. Live checks returned HTTP 200 for the
Hinglish budget query, the zero-match Voltas typo query and the AI-assisted
5-star query. The three-product Hinglish page returned IDs 40014, 39534 and
41715 at verified online prices INR 26,999, 39,999 and 35,499 respectively.
The default 24-candidate live page returned eight budget-qualified products in
10.09 seconds; three candidates exceeded the verification deadline and were
reported as unverified (`verification.complete=false`). Such a response is
partial, not proof that only eight products match. Retry to refresh verification.

The subsequent LLM interpretation fix passed 145 offline checks. Six real
Gemini interpretation probes covered `smart phone under 35000`, `samsng mobail
under 35000`, Hinglish/Hindi washing-machine descriptions, camera-use preference,
and `smart phone with 8GB RAM under 35000`. The probe scripts are
`artifacts/diagnose_search_ai.py` (interpretation) and
`artifacts/semantic_search_probe.py` (complete HTTP product retrieval).

The final eight-request HTTP smoke run returned real products for brand typo,
Hinglish/Hindi category descriptions, camera-use preference, explicit 8GB RAM,
and a repeated smart-phone query. A repeated specification query used
`interpretationSource=ai_cache` (2.39 seconds including fresh live verification).
The first smart-phone request fell back with `invalid_ai_output`; its later retry
succeeded with `interpretationSource=ai`. Provider output and latency can still
vary: fallback metadata must remain visible to API consumers. Saved complete
responses are in `artifacts/smart-search/llm-*.json`.

## Current LLM-first verification

The LLM-first revision passed 152 offline checks. The full original query is
sent to Gemini for every uncached search; there is no brand-specific expansion
table. The generated taxonomy now includes real indexed brand-category pairs.

Real HTTP checks returned the same three product IDs (42906, 41549, 42509) for
both `voltas washing machine` and `voltas beko washing machine`, with
`interpretationSource=ai` and no fallback. Times were 5.12 and 3.55 seconds.
The generic request disclosed Voltas → Voltas Beko in `brandResolution` and
`searchNotices`; product cards retained their actual brand. A repeated generic
query used `ai_cache` and took 1.94 seconds including fresh live prices.
`mobile under 35000` also used AI and returned verified budget matches.

The exact-brand control rejected an incompatible AI interpretation and used the
reported keyword fallback, preserving Voltas exactly and returning zero results.
Timeout/provider/validation fallback remains part of the public API contract.
Complete captures are `artifacts/smart-search/llm-first-*.json`, produced by
`artifacts/llm_first_probe.py`. No frontend changes are needed for the default
flow: pass the user's original query to the existing endpoint.

## Invalid-output diagnostics and bounded repair

`invalid_ai_output` means the provider response failed strict schema or query
grounding validation. It does not mean the catalogue is empty or the provider
timed out. Reproduced causes included a brand resolution whose output `brands`
array was empty, an inferred Apple brand for an explicit iPhone category, and
availability wording being treated as a mandatory product attribute.

Validation now logs a safe, server-owned rejection reason and attempt number,
without recording the raw query, provider output or credentials. An invalid
interpretation gets at most one repair request with validation feedback. Both
attempts share the existing `SMART_SEARCH_AI_TIMEOUT` deadline; there is no
second full timeout or chatbot conversation. Only a fully revalidated result is
cached. A timed-out worker retains its concurrency slot until it completes.

An inferred brand is accepted for an explicitly named category only when actual
catalogue brand-category pairs prove that category has a single owner. Generic
categories cannot introduce an arbitrary brand. Availability-question filler
does not discard product-family terms, colours, budgets or numeric specifications.
Persistent invalid output still returns keyword fallback with `fallbackReason`;
the endpoint and frontend response contract are unchanged.

The validation revision passed 157 offline tests, including bounded repair,
strict budget/specification rejection, safe logs, cache isolation and existing
chatbot checks. Six real provider interpretation probes passed validation.
Use `artifacts/validation_search_probe.py` for complete local HTTP verification;
captures are written to `artifacts/smart-search/validation-*.json`.

End-to-end checks returned HTTP 200 without fallback for iPhone, Voltas washing
machines (three real products), exact Voltas (valid zero matches), and smartphones
under INR 35,000 (verified prices INR 19,999 and 32,999). The exact-brand case
rejected the initial interpretation, repaired it within the same deadline and
returned `interpretationSource=ai`. The first Hinglish fridge check returned 503
because live prices were unavailable, independently of AI validation; it was not
reported as a successful empty result. Its retry returned HTTP 200 using the
validated interpretation cache and freshly verified prices INR 26,999 and 30,499.

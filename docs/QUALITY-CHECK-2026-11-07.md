# Quality check — 7 November 2026

Initial assessment: **needs fixes**. The original read-only review reproduced
three high-priority defects and two additional issues. The findings below
describe that original state; the subsequent fixes and verification follow here.

## Corrections following the review

Current status: **all five findings fixed and deployed**. API and worker run the
tested image; the original findings below are retained as the audit record.

| Finding | Corrected behavior |
| --- | --- |
| Full-catalog source failure | Unverified existing offers become `unknown` with a source error immediately. Independently confirmed offers in the same partial batch retain their status. Recovery does not generate a false restock. |
| Discovery prefilter | Description and category evidence accepted by the domain classifier also qualify a catalog candidate for detail fetching. |
| Trader pagination | Uses the shop's read-only AJAX category filter, persists form fields and page number across batches, and retains repeated-page protection. |
| Exact variants | Resolves a uniquely selected Shopify Offer before rejecting ambiguous parents; preserves variant price, packaging and per-variant GTIN evidence. Unresolved mixed pack sizes remain excluded. |
| Retry-After | Parses seconds and HTTP dates for 429/503, preserves the deadline in full and legacy scans, and defers watches during the requested wait. |

Verification of the corrected code:

- **24 new regression cases; 142 tests passed against isolated PostgreSQL**.
  The disposable test database and containers were removed afterward.
- Local suite: **140 passed, two PostgreSQL-only cases skipped**.
- Live Trader requests with a fresh client for each page returned four distinct
  Pokémon pages containing **50/50/50/2 products**, followed by the One Piece
  category with **41 products**. This verifies both the real pagination protocol
  and access to the following category, beyond mocked fixtures.
- Only Trader's incompatible old cursor was reset; all other merchant cursors
  were preserved. Existing unverified Trader offers from its earlier failures
  were marked unknown before starting the repaired import.
- Three production import batches advanced Trader to **page two and 62 checked
  products**, with zero source errors and zero unresolved offers at that snapshot.
  Page three and the One Piece category remained queued. Verification created no
  notifications; the normal worker resumed from the saved cursor afterward.
- Post-deployment public HTTPS health returned 200; unauthenticated shop access
  returned 401. The authenticated API exposed the repaired Trader progress.
  Both reported Spielewelt variants (`66340273488221`, `65644686180701`)
  returned freshly verified `out_of_stock` with no source error.
- The deployed source hashes match the tested local files. Database/source
  backups and the previous image were retained for rollback. `git diff --check`
  passed. No frontend implementation changed in these five corrections.

The original operational limits at the end of this report remain relevant:
these corrections do not establish that every catalog cycle is complete or
that every stored offer is fresh.

## Findings

### P1 — Failed full-catalog requests leave offers marked in stock

Location: `backend/app/scanner.py:122`.

Full-catalog adapters return `ScanResult.source_error` instead of raising. This
branch records a merchant error and schedules a retry, but does not invalidate
unverified offers. The legacy exception branch does call `mark_source_unknown`.

Reproduction: import an available product, then return HTTP 403 for the next
full-catalog request. The merchant error counter becomes one, while the public
offer still reports `in_stock` with `source_error: null` until its freshness
timeout. The existing failed-source regression test uses the legacy mode and
therefore does not cover this path.

Required change: propagate failed-source confidence to offers or their API
representation while preserving any independently verified offers from a
partially successful batch. Add a full-catalog outage regression test.

### P1 — Eligible products can disappear without a coverage warning

Location: `backend/app/adapters/structured_html.py:300`.

The full crawler prefilters candidates using packaging words in the title or
`product_type_hint`. The domain classifier also recognizes packaging from a
clear product description. These rules disagree.

Reproduction: a product named `Pokemon Testset` with description `Display mit
36 Booster, Deutsch` is accepted by `classify`, but the crawler imports zero
offers, reports the catalog complete, and records zero unresolved products.

Required change: account for the same description and category evidence used by
classification. Potentially relevant unresolved products should be counted,
rather than silently omitted from an apparently complete catalog.

### P1 — Trader-Online's live catalog is blocked after its first product page

Location: `backend/app/adapters/structured_html.py:256`.

Production reported three repeated-page errors. The pending URL was
`https://trader-online.de/pokemon/displays-boxen/2`; the server redirects it to
the trailing-slash version, whose canonical URL and products still describe the
first page. The actual shop pagination has controls for pages 1–4 without anchor
links. Reading only `<link rel="next" href="2">` does not operate that pagination.
The queued One Piece category is also left waiting behind this failing page.

Required change: implement the shop's real pagination mechanism and retain the
loop guard. A live verification must prove that page two contains different
products and that the next category can be reached.

### P2 — A selected variant is rejected when JSON-LD lists multiple offers

Location: `backend/app/adapters/structured_html.py:91`.

`len(concrete) != 1` rejects the product before the requested `?variant=...` is
examined. Even two offers with distinct variant URLs and explicit names/prices
cannot be monitored using an exact variant link. The adapter returns no offer.

Required change: resolve an explicitly selected, uniquely identified offer before
deciding the parent is ambiguous. Preserve the rejection of unresolved parent
minimum prices and mixed packaging.

### P2 — HTTP-date Retry-After values are not honored

Location: `backend/app/adapters/base.py:114`.

Only a digit string is treated as Retry-After. A valid HTTP date is replaced by
30 seconds. Reproduction with a date twenty minutes in the future recorded a
30-second retry hint; the scanner would retry after its shorter local backoff,
before the shop's requested time.

Required change: parse both delay-seconds and HTTP-date forms, and schedule the
next request no earlier than that deadline.

## Checks performed

- Packaged backend against isolated PostgreSQL: **118 passed**; the temporary
  test project was removed afterward.
- Local backend: **116 passed, two PostgreSQL-only tests skipped**.
- Frontend TypeScript check and production build: passed.
- `git diff --check`: passed.
- Public HTTPS health and API authentication: passed; unauthenticated shop data
  access returned HTTP 401.
- Fresh read-only product checks: **31 samples across all 18 active shops**.
  Stored variant IDs, prices and availability matched fresh configured-source
  results in every sample. This checks consistency with those sources; it does
  not independently prove checkout or shipping availability for every merchant.
- The two reported Spielewelt variants still returned fresh `out_of_stock`
  through the public API, with no source error.
- Separate local reproductions confirmed all four deterministic code cases
  above. Trader-Online's pagination failure was observed directly in production.

## Operational limits observed

At the production snapshot there were **2,536 visible offers**, of which **605
(about 24%) were older than the 30-minute freshness threshold**. The API marks
these stale observations unknown. CrispyCards had no fresh stored offers at that
moment, despite successful discovery batches, because the broad discovery pass
had not revisited its previously imported products.

Full catalog discovery and frequent refresh of already known offers currently
share the same single-worker queue. Large HTML catalogs therefore need a
separate refresh strategy if the nominal shop interval is expected to describe
every product's stock freshness. At the snapshot Card-Corner also had 33
explicit unresolved product offers. These are coverage gaps, not successful
full coverage.

Live counts are time-dependent. Passing tests and matching samples do not remove
the reproduced defects or establish that all catalog cycles have finished.

# BinWise Fallback Wine List Search

## Overview

Many restaurants publish their wine lists on **BinWise** (hub.binwise.com) even when they do not link to them from their own website. The crawler can discover these “hidden” lists by searching Google for pages on BinWise’s domain that match the restaurant name.

The **BinWise fallback** is a workflow step that runs when the normal path does not yield a wine list: it performs a Google site search, validates that the result belongs to the correct restaurant, and then downloads the list if found.

## When It Runs

The BinWise search node is used in three situations:

1. **No restaurant website** – The Michelin page for the restaurant has no website URL. The workflow goes directly to BinWise search instead of crawling a site.
2. **No wine list found on the website** – The restaurant’s site was crawled (tiers 1–3 of the finder) but no wine list URL was found. The workflow then tries BinWise before giving up.
3. **Download failed** – A wine list URL was found (on the site or from a previous BinWise run) but the download failed. The workflow tries BinWise once; if the BinWise result also fails to download, it does not retry to avoid a loop.

A `binwise_searched` flag in workflow state ensures we only attempt the BinWise search once per restaurant per run.

## How the Search Works

### Two-pass strategy

The search uses two Google queries in order:

1. **Pass 1 (prefer PDF):**  
   `site:hub.binwise.com "Restaurant Name" pdf`  
   Aims at direct PDF wine lists on BinWise. If any result validates (see below), that URL is used and pass 2 is skipped.

2. **Pass 2 (HTML fallback):**  
   `site:hub.binwise.com "Restaurant Name"`  
   Used only if pass 1 returns no validated result. Targets HTML/digital menu pages on BinWise.

If both passes yield no validated result, the crawler records that no wine list was found for that restaurant.

### Result validation

Google can return BinWise pages for a *different* restaurant when the name partially matches. To avoid attaching the wrong list:

- Each candidate URL is fetched with `httpx`.
- The page is parsed (BeautifulSoup); the `<title>` and `<h1>`/`<h2>` text are collected.
- The restaurant name is normalized (lowercase, punctuation stripped, whitespace collapsed).
- **Short names (1–2 significant words):** The full normalized name must appear as a substring in the combined title/heading text.
- **Longer names:** Every significant word (excluding stop words like “the”, “restaurant”, “&”) must appear in that text.

Only the first result that passes this check is used. If none do, the next result or the next pass is tried.

### Implementation details

- Search is implemented via the **googlesearch-python** library (no API key).
- Only URLs under `hub.binwise.com` are considered.
- There is a short delay between the two passes to reduce the chance of rate limiting.
- Network or validation failures are handled so the workflow continues (e.g. no wine list found or save result).

## Configuration

| Setting                | Type    | Default | Description |
|------------------------|---------|---------|-------------|
| `WINERANK_USE_BINWISE_SEARCH` | boolean | `true`  | Enable or disable the BinWise fallback. When `false`, the workflow never runs the BinWise search node. |

Set in `.env` or environment:

```bash
# Disable BinWise fallback
WINERANK_USE_BINWISE_SEARCH=false
```

## Workflow position

Rough flow with BinWise:

```
process_restaurant
    ├── has website     → crawl_restaurant_site
    │                        ├── wine list URL found → download_wine_list → …
    │                        └── no URL             → search_binwise
    └── no website       → search_binwise

search_binwise
    ├── URL found   → download_wine_list → …
    └── not found   → save_result

download_wine_list (on failure)
    ├── binwise_searched false → search_binwise
    └── binwise_searched true  → save_result
```

## Code and tests

- **Search and validation:** `src/winerank/crawler/binwise_search.py`  
  - `search_binwise(restaurant_name)` – public entry used by the workflow.  
  - `_validate_binwise_result(url, restaurant_name)` – checks that the page is for the right restaurant.
- **Workflow:** `src/winerank/crawler/workflow.py`  
  - Node: `search_binwise_node`  
  - Routing: `_route_after_process`, `_route_after_crawl`, `_route_after_download`, `_route_after_binwise`
- **Tests:**  
  - `tests/test_binwise_search.py` – validation and two-pass search behavior.  
  - `tests/test_workflow_routing.py` – routing when there is no website, no wine list URL, or download failure.

## Dependencies

- **googlesearch-python** (≥1.3) – used to run the Google queries.  
  If it is not installed, the BinWise search is effectively disabled (the node runs but returns no URL).

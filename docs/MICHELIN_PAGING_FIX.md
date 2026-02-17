# Michelin Pagination Fix

## Issue

The crawler was repeatedly fetching the same Michelin listing page, resulting in duplicate restaurants appearing in the logs and database.

## Root Cause

When the workflow completed all restaurants on a page and routed to "next_page", it returned to `fetch_listing_page_node` with the **same** `current_page` value in state. This caused the following sequence:

1. **Page 1 completed**: After processing all restaurants on page 1, `_route_after_save` correctly returned `"next_page"`
2. **State unchanged**: The router doesn't modify state, so `state["current_page"]` was still `1`
3. **Re-fetch page 1**: In `fetch_listing_page_node`, we read `cur_page = state["current_page"]` (still 1) and fetched page 1 again
4. **Loop**: This repeated indefinitely for page 1

The problem was that `fetch_listing_page_node` only updated `current_page` in state when the **circuit breaker** tripped (error path), but never in the **success path**.

## Solution

In `fetch_listing_page_node`, detect when we're being called after exhausting the current page and advance to the next page:

```python
# Determine which page to fetch
urls_so_far = state.get("restaurant_urls") or []
idx_so_far = state.get("current_restaurant_idx", 0)
cur_page = state["current_page"]

# If we finished all restaurants on the current page and routed here for "next page",
# advance to the next page number (since we don't update current_page in success path).
if len(urls_so_far) > 0 and idx_so_far >= len(urls_so_far):
    cur_page = cur_page + 1
```

Then persist this page in the state updates:

```python
updates: dict = {
    "current_page": cur_page,  # Persist the page we actually fetched
    "restaurant_urls": result["restaurant_urls"],
    # ...
}
```

## How It Works

### First call (page 1)
- `urls_so_far = []` (empty from init)
- Condition `len(urls_so_far) > 0` is False
- `cur_page` stays 1
- Fetch page 1, return `current_page: 1`

### After finishing page 1
- Router returns `"next_page"` because `idx >= total` and `current_page + 1 <= total_pages`
- State has `current_page: 1`, `restaurant_urls: [48 URLs]`, `current_restaurant_idx: 48`
- Enter `fetch_listing_page_node` again

### Second call (page 2)
- `urls_so_far = [48 URLs]`, `idx_so_far = 48`, `cur_page = 1`
- Condition: `len(urls_so_far) > 0` (48 > 0) AND `idx_so_far >= len(urls_so_far)` (48 >= 48)
- **Advance**: `cur_page = 2`
- Fetch page 2, return `current_page: 2`

### Circuit breaker case
- When circuit breaker trips, we already return `current_page: cur_page + 1`
- Next call has `urls_so_far = []` (empty because error), so condition is False
- We use the already-advanced `current_page` from state

## Testing

### New Tests Added

Added comprehensive test suite in `tests/test_workflow_circuit_breaker.py`:

**`TestFetchListingPagePagingAdvancement`** (5 tests):
1. ✅ `test_first_page_fetch_does_not_advance_page` - Initial fetch with empty state uses page 1
2. ✅ `test_after_finishing_page_advances_to_next_page` - After processing all restaurants on page 1, advances to page 2
3. ✅ `test_middle_of_page_does_not_advance` - When idx < len(urls), stays on current page
4. ✅ `test_advances_through_multiple_pages` - Page 2 → Page 3 advancement works
5. ✅ `test_circuit_breaker_already_advanced_does_not_double_advance` - When circuit breaker already advanced the page, doesn't advance again

### Existing Tests

All existing tests continue to pass:
- ✅ 19 workflow routing tests
- ✅ 7 circuit breaker and browser recovery tests
- ✅ Doesn't break single-page crawls
- ✅ Doesn't break circuit breaker logic
- ✅ Works with single-restaurant mode (bypasses this logic)

**Total: 31 tests passing**

## Files Changed

- `src/winerank/crawler/workflow.py`:
  - Lines 354-362: Added page advance detection logic
  - Line 370: Added `current_page` to success path updates

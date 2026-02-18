"""LangGraph workflow for restaurant crawler with PostgreSQL checkpointing."""
import logging
import time
from datetime import datetime, timezone
from typing import Any, TypedDict, Optional, List, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from playwright.sync_api import sync_playwright, Browser, Page

from winerank.config import get_settings
from winerank.common.db import get_session, resolve_restaurant_by_id_or_name
from winerank.common.models import (
    Restaurant,
    WineList,
    Job,
    SiteOfRecord,
    CrawlStatus,
    JobStatus,
)
from winerank.crawler.michelin import MichelinScraper
from winerank.crawler.restaurant_finder import RestaurantWineListFinder
from winerank.crawler.downloader import WineListDownloader
from winerank.crawler.text_extractor import WineListTextExtractor
from winerank.crawler.binwise_search import search_binwise


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared browser context – managed by run_crawler(), used by every node
# ---------------------------------------------------------------------------
_playwright_instance: Optional[object] = None  # Playwright from sync_playwright()
_browser: Optional[Browser] = None
_browser_page: Optional[Page] = None


def _get_page() -> Page:
    """Return the shared Playwright Page.  Raises if not initialised."""
    if _browser_page is None:
        raise RuntimeError("Browser page not initialised – call run_crawler()")
    return _browser_page


def _recover_browser() -> None:
    """Restart the entire Chromium browser after a crash.

    Closes the old browser (which may be in a broken state) and launches
    a fresh one from the existing Playwright instance.  All three
    module-level refs are updated.
    """
    global _browser_page, _browser

    if not _playwright_instance:
        logger.error("No Playwright instance available -- cannot recover browser")
        return

    settings = get_settings()

    # 1. Tear down the old browser gracefully
    for label, closeable in [("page", _browser_page), ("browser", _browser)]:
        try:
            if closeable:
                closeable.close()
        except Exception:
            logger.info("Ignoring error closing %s during recovery", label)

    # 2. Launch a brand-new browser + page
    try:
        logger.info("Restarting Chromium browser (headless=%s) ...", settings.headless)
        pw = cast(Any, _playwright_instance)
        new_browser = pw.chromium.launch(headless=settings.headless)
        _browser = new_browser
        _browser_page = new_browser.new_page()
        logger.info("Browser restarted successfully")
    except Exception as exc:
        logger.error("Browser restart failed: %s", exc)
        _browser = None
        _browser_page = None


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------

class CrawlerState(TypedDict):
    """State for crawler workflow."""
    job_id: int
    michelin_level: str
    site_of_record_id: int

    # Behaviour flags
    force_recrawl: bool

    # Single-restaurant filter (ID or name).  When set, the Michelin listing
    # scrape is bypassed and the restaurant is loaded directly from the DB.
    restaurant_filter: Optional[str]

    # Pagination
    total_pages: int
    current_page: int

    # Restaurant queue for current page
    restaurant_urls: List[str]
    current_restaurant_idx: int

    # Current restaurant context
    current_restaurant: Optional[dict]

    # Counters
    restaurants_found: int
    restaurants_processed: int
    wine_lists_downloaded: int
    wine_list_restaurant_names: List[str]  # names of restaurants with lists downloaded this run
    errors: List[str]

    # Circuit breaker: consecutive failures on current listing page
    consecutive_fetch_failures: int
    max_consecutive_failures: int

    # BinWise fallback: whether search was already attempted for current restaurant
    binwise_searched: bool


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def create_crawler_workflow() -> StateGraph:
    """Create the LangGraph crawler workflow."""

    workflow = StateGraph(CrawlerState)

    # Nodes
    workflow.add_node("init_job", init_job_node)
    workflow.add_node("fetch_listing_page", fetch_listing_page_node)
    workflow.add_node("process_restaurant", process_restaurant_node)
    workflow.add_node("crawl_restaurant_site", crawl_restaurant_site_node)
    workflow.add_node("search_binwise", search_binwise_node)
    workflow.add_node("download_wine_list", download_wine_list_node)
    workflow.add_node("extract_text", extract_text_node)
    workflow.add_node("save_result", save_result_node)
    workflow.add_node("complete_job", complete_job_node)

    # Entry
    workflow.set_entry_point("init_job")

    # Edges
    workflow.add_edge("init_job", "fetch_listing_page")
    workflow.add_edge("fetch_listing_page", "process_restaurant")

    # After processing a restaurant, decide: crawl its site, search BinWise, or save.
    workflow.add_conditional_edges(
        "process_restaurant",
        _route_after_process,
        {
            "crawl_site": "crawl_restaurant_site",
            "search_binwise": "search_binwise",
            "save_result": "save_result",
        },
    )

    # After crawling the restaurant site, decide: download or try BinWise.
    workflow.add_conditional_edges(
        "crawl_restaurant_site",
        _route_after_crawl,
        {
            "download": "download_wine_list",
            "search_binwise": "search_binwise",
            "save_result": "save_result",
        },
    )

    # After BinWise search, download if URL found else save.
    workflow.add_conditional_edges(
        "search_binwise",
        _route_after_binwise,
        {
            "download": "download_wine_list",
            "save_result": "save_result",
        },
    )

    # After download: extract text on success, else try BinWise or save.
    workflow.add_conditional_edges(
        "download_wine_list",
        _route_after_download,
        {
            "extract_text": "extract_text",
            "search_binwise": "search_binwise",
            "save_result": "save_result",
        },
    )

    workflow.add_edge("extract_text", "save_result")

    # After saving, loop back or finish.
    workflow.add_conditional_edges(
        "save_result",
        _route_after_save,
        {
            "next_restaurant": "process_restaurant",
            "next_page": "fetch_listing_page",
            "done": "complete_job",
        },
    )

    workflow.add_edge("complete_job", END)

    return workflow


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def _route_after_process(state: CrawlerState) -> str:
    """After process_restaurant – crawl the site if it has a website.

    Restaurants whose wine list was already found in a previous run are
    skipped unless ``force_recrawl`` is set in the workflow state.
    """
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return "save_result"

    # Skip restaurants that already have a wine list (but not failed ones)
    if (
        restaurant.get("crawl_status") == CrawlStatus.WINE_LIST_FOUND
        and not state.get("force_recrawl")
    ):
        logger.info(
            "Skipping %s – wine list already found", restaurant.get("name")
        )
        return "save_result"

    if restaurant.get("website_url"):
        return "crawl_site"
    return "search_binwise"


def _route_after_crawl(state: CrawlerState) -> str:
    """After crawl_restaurant_site – download if wine list URL was found."""
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return "save_result"
    if restaurant.get("wine_list_url"):
        return "download"
    return "search_binwise"


def _route_after_download(state: CrawlerState) -> str:
    """After download_wine_list – extract text on success, else try BinWise or save."""
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return "save_result"
    if restaurant.get("local_file_path") and not restaurant.get("download_failed"):
        return "extract_text"
    if restaurant.get("download_failed"):
        if state.get("binwise_searched"):
            return "save_result"
        return "search_binwise"
    return "save_result"


def _route_after_binwise(state: CrawlerState) -> str:
    """After search_binwise – download if URL found, else save result."""
    restaurant = state.get("current_restaurant")
    if restaurant and restaurant.get("wine_list_url"):
        return "download"
    return "save_result"


def _route_after_save(state: CrawlerState) -> str:
    """After save_result – next restaurant, next page, or done."""
    idx = state["current_restaurant_idx"]
    total = len(state["restaurant_urls"])

    # Circuit-breaker path: page was skipped due to repeated failures
    failures = state.get("consecutive_fetch_failures", 0)
    max_failures = state.get("max_consecutive_failures", 3)
    if failures >= max_failures and total == 0:
        # current_page was already advanced when breaker tripped
        if state["total_pages"] > 0 and state["current_page"] <= state["total_pages"]:
            logger.info("Advancing past failed page to page %d", state["current_page"])
            return "next_page"
        return "done"

    if idx < total:
        return "next_restaurant"

    # All restaurants on this page done – try next page
    next_page = state["current_page"] + 1
    if state["total_pages"] > 0 and next_page <= state["total_pages"]:
        return "next_page"

    return "done"


# ---------------------------------------------------------------------------
# Node implementations
# ---------------------------------------------------------------------------

def init_job_node(state: CrawlerState) -> dict:
    """Initialize or resume a crawler job."""
    settings = get_settings()

    with get_session() as session:
        # Resume path
        if state.get("job_id"):
            job = session.query(Job).filter_by(id=state["job_id"]).first()
            if job:
                job.status = JobStatus.RUNNING
                session.commit()
                return {}                   # keep existing state unchanged

        # New job: site_of_record_id must be provided by CLI
        site_of_record_id = state.get("site_of_record_id")
        if not site_of_record_id:
            raise ValueError(
                "site_of_record_id is required for new jobs. "
                "Pass --site when running the crawler."
            )
        site = session.query(SiteOfRecord).filter_by(id=site_of_record_id).first()
        if not site:
            raise ValueError(f"Site of record id={site_of_record_id} not found.")

        michelin_level = state.get("michelin_level", settings.michelin_level)

        job = Job(
            job_type="crawler",
            michelin_level=michelin_level,
            status=JobStatus.RUNNING,
            site_of_record_id=site.id,
        )
        session.add(job)
        session.commit()

        return {
            "job_id": job.id,
            "michelin_level": michelin_level,
            "site_of_record_id": site.id,
            "force_recrawl": state.get("force_recrawl", False),
            "restaurant_filter": state.get("restaurant_filter"),
            "total_pages": 0,
            "current_page": 1,
            "restaurant_urls": [],
            "current_restaurant_idx": 0,
            "current_restaurant": None,
            "restaurants_found": 0,
            "restaurants_processed": 0,
            "wine_lists_downloaded": 0,
            "wine_list_restaurant_names": [],
            "errors": [],
            "consecutive_fetch_failures": 0,
            "max_consecutive_failures": 3,
            "binwise_searched": False,
        }


def _resolve_restaurant_filter(
    filter_value: str,
    site_of_record_id: Optional[int] = None,
) -> Optional[Restaurant]:
    """Look up a restaurant by ID (if numeric) or name (case-insensitive).

    When site_of_record_id is set, name resolution is scoped to that site.
    """
    return resolve_restaurant_by_id_or_name(filter_value, site_of_record_id=site_of_record_id)


def fetch_listing_page_node(state: CrawlerState) -> dict:
    """Fetch a Michelin listing page and extract restaurant URLs.

    When ``restaurant_filter`` is set, bypasses Michelin scraping entirely
    and loads the restaurant directly from the database.
    """
    # --- Single-restaurant mode ---
    restaurant_filter = state.get("restaurant_filter")
    if restaurant_filter:
        rec = _resolve_restaurant_filter(
            restaurant_filter,
            site_of_record_id=state.get("site_of_record_id"),
        )
        if not rec:
            msg = f"Restaurant not found for filter: {restaurant_filter}"
            logger.error(msg)
            return {
                "restaurant_urls": [],
                "current_restaurant_idx": 0,
                "restaurants_found": 0,
                "total_pages": 1,
                "errors": state.get("errors", []) + [msg],
            }

        # Always load from DB in single-restaurant mode (skip Michelin scrape)
        url_token = f"__direct__:{rec.id}"
        logger.info(
            "Single-restaurant mode: %s (id=%d)", rec.name, rec.id,
        )
        return {
            "restaurant_urls": [url_token],
            "current_restaurant_idx": 0,
            "restaurants_found": 1,
            "total_pages": 1,
        }

    # --- Normal Michelin listing mode ---
    with get_session() as session:
        site = session.query(SiteOfRecord).filter_by(
            id=state["site_of_record_id"]
        ).first()
        if not site:
            raise ValueError(
                f"Site of record id={state['site_of_record_id']} not found."
            )
        base_url = site.site_url
    page = _get_page()
    scraper = MichelinScraper(page, base_url=base_url)

    # Determine which page to fetch
    urls_so_far = state.get("restaurant_urls") or []
    idx_so_far = state.get("current_restaurant_idx", 0)
    cur_page = state["current_page"]
    
    # If we finished all restaurants on the current page and routed here for "next page",
    # advance to the next page number (since we don't update current_page in success path).
    if len(urls_so_far) > 0 and idx_so_far >= len(urls_so_far):
        cur_page = cur_page + 1

    try:
        url = scraper.get_listing_url(state["michelin_level"], cur_page)
        logger.info("Fetching listing page %d: %s", cur_page, url)
        result = scraper.scrape_listing_page(url)

        updates: dict = {
            "current_page": cur_page,  # Persist the page we actually fetched
            "restaurant_urls": result["restaurant_urls"],
            "current_restaurant_idx": 0,
            "restaurants_found": state["restaurants_found"]
                                + len(result["restaurant_urls"]),
            "consecutive_fetch_failures": 0,
        }

        if cur_page == 1:
            updates["total_pages"] = result["total_pages"]

        # Persist progress
        with get_session() as session:
            job = session.query(Job).filter_by(id=state["job_id"]).first()
            if job:
                job.total_pages = updates.get("total_pages", state.get("total_pages", 0))
                job.current_page = cur_page
                job.restaurants_found = updates["restaurants_found"]

        logger.info(
            "Found %d restaurant URLs on page %d (total so far: %d)",
            len(result["restaurant_urls"]),
            cur_page,
            updates["restaurants_found"],
        )
        return updates

    except Exception as e:
        logger.error("Error fetching listing page %d: %s", cur_page, e)

        max_failures = state.get("max_consecutive_failures", 3)
        base = state.get("consecutive_fetch_failures", 0)
        # After a circuit-breaker skip we have base >= max_failures; treat as new page
        if base >= max_failures:
            base = 0
        failures = base + 1

        error_msg = f"Page {cur_page} attempt {failures}: {e}"
        errors = state.get("errors", []) + [error_msg]

        # Attempt browser recovery on crash-class errors
        error_str = str(e)
        if "Page crashed" in error_str or "Page closed" in error_str:
            logger.info("Browser crash detected on attempt %d -- recovering browser", failures)
            _recover_browser()

        if failures >= max_failures:
            logger.error(
                "Circuit breaker tripped: %d consecutive failures on page %d -- skipping",
                max_failures, cur_page,
            )
            # Keep consecutive_fetch_failures so _route_after_save can detect skip; advance page
            return {
                "consecutive_fetch_failures": failures,
                "errors": errors,
                "restaurant_urls": [],
                "current_restaurant_idx": 0,
                "current_page": cur_page + 1,
            }

        return {
            "consecutive_fetch_failures": failures,
            "errors": errors,
        }


def _load_restaurant_from_db(restaurant_id: int) -> Optional[dict]:
    """Load restaurant fields from the DB into a dict suitable for state."""
    with get_session() as session:
        rec = session.query(Restaurant).filter_by(id=restaurant_id).first()
        if not rec:
            return None
        return {
            "id": rec.id,
            "name": rec.name,
            "michelin_url": rec.michelin_url,
            "website_url": rec.website_url,
            "wine_list_url": rec.wine_list_url,
            "michelin_distinction": (
                getattr(rec.michelin_distinction, "value", None)
            ),
            "address": rec.address,
            "city": rec.city,
            "state": rec.state,
            "zip_code": rec.zip_code,
            "country": rec.country,
            "cuisine": rec.cuisine,
            "price_range": rec.price_range,
            "crawl_status": rec.crawl_status,
        }


def process_restaurant_node(state: CrawlerState) -> dict:
    """Visit a Michelin restaurant page and extract details.

    In single-restaurant mode (URLs starting with ``__direct__:``), the
    restaurant is loaded directly from the database instead of scraping
    Michelin.
    """
    idx = state["current_restaurant_idx"]
    urls = state["restaurant_urls"]

    if idx >= len(urls):
        return {"current_restaurant": None}

    restaurant_url = urls[idx]

    # --- Direct DB lookup (single-restaurant mode) ---
    if restaurant_url.startswith("__direct__:"):
        rest_id = int(restaurant_url.split(":", 1)[1])
        data = _load_restaurant_from_db(rest_id)
        if data:
            logger.info(
                "Restaurant (direct): %s | website: %s",
                data["name"], data.get("website_url") or "NONE",
            )
            return {"current_restaurant": data, "binwise_searched": False}
        logger.error("Restaurant id=%d not found in DB", rest_id)
        return {
            "current_restaurant": None,
            "errors": state.get("errors", [])
                     + [f"Restaurant id={rest_id} not found"],
        }

    # --- Normal Michelin scrape path ---
    with get_session() as session:
        site = session.query(SiteOfRecord).filter_by(
            id=state["site_of_record_id"]
        ).first()
        if not site:
            raise ValueError(
                f"Site of record id={state['site_of_record_id']} not found."
            )
        base_url = site.site_url
        # Derive country from site name, e.g. "Michelin Guide USA" -> "USA"
        site_country = site.site_name.replace("Michelin Guide ", "", 1)
    page = _get_page()
    scraper = MichelinScraper(page, base_url=base_url)

    try:
        logger.info("Processing restaurant %d/%d: %s",
                     idx + 1, len(urls), restaurant_url)
        data = scraper.scrape_restaurant_detail(restaurant_url)
        data["country"] = data.get("country") or site_country

        # Upsert restaurant in database
        with get_session() as session:
            existing = session.query(Restaurant).filter_by(
                michelin_url=restaurant_url
            ).first()

            if existing:
                data["id"] = existing.id
                data["crawl_status"] = existing.crawl_status
                data["wine_list_url"] = existing.wine_list_url
                # Refresh address fields from the latest scrape
                existing.address = data.get("address") or existing.address
                existing.city = data.get("city") or existing.city
                existing.state = data.get("state") or existing.state
                existing.zip_code = data.get("zip_code") or existing.zip_code
                existing.country = data.get("country") or existing.country
                session.commit()
            else:
                restaurant = Restaurant(
                    name=data["name"],
                    michelin_url=data["michelin_url"],
                    website_url=data["website_url"],
                    michelin_distinction=data["michelin_distinction"],
                    address=data.get("address"),
                    city=data["city"],
                    state=data["state"],
                    zip_code=data.get("zip_code"),
                    country=data["country"],
                    cuisine=data["cuisine"],
                    price_range=data["price_range"],
                    crawl_status=(
                        CrawlStatus.HAS_WEBSITE
                        if data["website_url"]
                        else CrawlStatus.NO_WEBSITE
                    ),
                    site_of_record_id=state["site_of_record_id"],
                )
                session.add(restaurant)
                session.commit()
                data["id"] = restaurant.id

        logger.info(
            "Restaurant: %s | website: %s",
            data["name"],
            data.get("website_url") or "NONE",
        )
        return {"current_restaurant": data, "binwise_searched": False}

    except Exception as e:
        logger.error("Error processing %s: %s", restaurant_url, e)
        return {
            "current_restaurant": None,
            "errors": state.get("errors", []) + [str(e)],
        }


def _country_to_language_hint(country: Optional[str]) -> str:
    """Map restaurant country to language hint for wine list discovery (fr/es/en)."""
    if not country:
        return "en"
    c = str(country).strip().lower()
    if c == "france":
        return "fr"
    if c in ("spain", "mexico"):
        return "es"
    return "en"


def crawl_restaurant_site_node(state: CrawlerState) -> dict:
    """Navigate a restaurant website to locate its wine list."""
    restaurant = state["current_restaurant"]
    if not restaurant or not restaurant.get("website_url"):
        return {}

    page = _get_page()
    finder = RestaurantWineListFinder(page)
    language_hint = _country_to_language_hint(restaurant.get("country"))

    # Start timing
    start_time = time.time()
    
    try:
        # Check for cached wine list URL
        cached_url = None
        with get_session() as session:
            rec = session.query(Restaurant).filter_by(
                id=restaurant["id"]
            ).first()
            if rec:
                cached_url = rec.wine_list_url

        logger.info("Crawling %s website: %s",
                     restaurant["name"], restaurant["website_url"])
        wine_list_url = finder.find_wine_list(
            restaurant["website_url"],
            cached_wine_list_url=cached_url,
            language_hint=language_hint,
        )

        # Calculate crawl duration
        crawl_duration = time.time() - start_time
        
        # Capture metrics
        tokens_used = finder.tokens_used
        pages_visited = finder.pages_loaded

        if wine_list_url:
            logger.info("  -> Found wine list: %s", wine_list_url)
        else:
            logger.info("  -> No wine list found")
        
        logger.info("  -> Crawl metrics: %.2fs, %d pages, %d tokens",
                    crawl_duration, pages_visited, tokens_used)

        # Store metrics in restaurant dict for later persistence
        updated_restaurant = {
            **restaurant,
            "wine_list_url": wine_list_url,
            "crawl_duration_seconds": round(crawl_duration, 2),
            "llm_tokens_used": tokens_used,
            "pages_visited": pages_visited,
        }

        return {
            "current_restaurant": updated_restaurant,
        }

    except Exception as e:
        # Still capture timing even on error
        crawl_duration = time.time() - start_time
        
        logger.error("Error crawling %s: %s", restaurant.get("name"), e)
        return {
            "current_restaurant": {
                **restaurant,
                "wine_list_url": None,
                "crawl_duration_seconds": round(crawl_duration, 2),
                "llm_tokens_used": getattr(finder, "tokens_used", 0),
                "pages_visited": getattr(finder, "pages_loaded", 0),
            },
            "errors": state.get("errors", []) + [str(e)],
        }


def search_binwise_node(state: CrawlerState) -> dict:
    """Try to find a BinWise-hosted wine list via Google search."""
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return {"binwise_searched": True}

    settings = get_settings()
    if not getattr(settings, "use_binwise_search", True):
        logger.info("BinWise search disabled – skipping for %s", restaurant.get("name"))
        return {"binwise_searched": True}

    name = restaurant.get("name") or ""
    if not name.strip():
        return {"binwise_searched": True}

    logger.info("BinWise fallback search for %s", name)
    url = search_binwise(name)

    if url:
        logger.info("BinWise result for %s: %s", name, url)
        return {
            "current_restaurant": {**restaurant, "wine_list_url": url},
            "binwise_searched": True,
        }

    logger.info("No BinWise wine list found for %s", name)
    return {
        "current_restaurant": {**restaurant, "wine_list_url": None},
        "binwise_searched": True,
    }


def download_wine_list_node(state: CrawlerState) -> dict:
    """Download the wine list file."""
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return {}
    wine_list_url = restaurant.get("wine_list_url")
    if not wine_list_url:
        return {}

    try:
        page = _get_page()
        downloader = WineListDownloader(page=page)
        slug = restaurant["name"].lower().replace(" ", "-").replace("'", "")

        logger.info("Downloading wine list for %s from %s",
                     restaurant["name"], wine_list_url)
        result = downloader.download_wine_list_sync(wine_list_url, slug)

        # Persist WineList row
        with get_session() as session:
            wine_list = WineList(
                restaurant_id=restaurant["id"],
                list_name=f"{restaurant['name']} Wine List",
                source_url=wine_list_url,
                local_file_path=result["local_file_path"],
                file_hash=result["file_hash"],
                wine_count=0,
            )
            session.add(wine_list)
            session.commit()
            result["wine_list_id"] = wine_list.id

        merged = dict(restaurant)
        merged.update(result)
        names = (state.get("wine_list_restaurant_names") or []) + [restaurant["name"]]
        return {
            "current_restaurant": merged,
            "wine_lists_downloaded": (state.get("wine_lists_downloaded") or 0) + 1,
            "wine_list_restaurant_names": names,
        }

    except Exception as e:
        logger.error("Error downloading %s: %s", wine_list_url, e)
        merged = dict(restaurant)
        merged["download_failed"] = True
        return {
            "current_restaurant": merged,
            "errors": (state.get("errors") or []) + [str(e)],
        }


def extract_text_node(state: CrawlerState) -> dict:
    """Extract structured text from the downloaded wine list."""
    restaurant = state.get("current_restaurant")
    if not restaurant:
        return {}
    path = restaurant.get("local_file_path")
    if not path:
        return {}

    try:
        extractor = WineListTextExtractor()
        text_path = extractor.extract_and_save(path)

        with get_session() as session:
            wl_id = restaurant.get("wine_list_id")
            if wl_id:
                wl = session.query(WineList).filter_by(id=wl_id).first()
                if wl:
                    wl.text_file_path = text_path

        merged = dict(restaurant)
        merged["text_file_path"] = text_path
        return {"current_restaurant": merged}

    except Exception as e:
        logger.error("Error extracting text from %s: %s", path, e)
        return {"errors": (state.get("errors") or []) + [str(e)]}


def save_result_node(state: CrawlerState) -> dict:
    """Persist the crawl outcome and advance the restaurant index."""
    restaurant = state.get("current_restaurant")

    # Detect skipped restaurants: crawl_status already set from DB and no
    # new crawl was performed (no crawl_duration_seconds).  Don't touch
    # the DB record – just advance the index.
    skipped = (
        restaurant
        and restaurant.get("crawl_status") == CrawlStatus.WINE_LIST_FOUND
        and restaurant.get("crawl_duration_seconds") is None
    )

    if restaurant and restaurant.get("id"):
        try:
            with get_session() as session:
                if not skipped:
                    rec = session.query(Restaurant).filter_by(
                        id=restaurant["id"]
                    ).first()
                    if rec:
                        if restaurant.get("download_failed"):
                            rec.crawl_status = CrawlStatus.DOWNLOAD_LIST_FAILED
                            rec.wine_list_url = restaurant.get("wine_list_url")
                        elif restaurant.get("wine_list_url") and restaurant.get("local_file_path"):
                            rec.crawl_status = CrawlStatus.WINE_LIST_FOUND
                            rec.wine_list_url = restaurant["wine_list_url"]
                        elif restaurant.get("wine_list_url"):
                            rec.crawl_status = CrawlStatus.DOWNLOAD_LIST_FAILED
                            rec.wine_list_url = restaurant["wine_list_url"]
                        elif restaurant.get("website_url"):
                            rec.crawl_status = CrawlStatus.NO_WINE_LIST
                        else:
                            rec.crawl_status = CrawlStatus.NO_WEBSITE
                        rec.last_crawled_at = datetime.now(timezone.utc)

                        # Persist crawl metrics
                        if restaurant.get("crawl_duration_seconds") is not None:
                            rec.crawl_duration_seconds = restaurant["crawl_duration_seconds"]
                        if restaurant.get("llm_tokens_used") is not None:
                            rec.llm_tokens_used = restaurant["llm_tokens_used"]
                        if restaurant.get("pages_visited") is not None:
                            rec.pages_visited = restaurant["pages_visited"]

                # Always update job progress (including skipped restaurants)
                job = session.query(Job).filter_by(
                    id=state["job_id"]
                ).first()
                if job:
                    job.restaurants_processed = state["restaurants_processed"] + 1
                    job.wine_lists_downloaded = state["wine_lists_downloaded"]

        except Exception as e:
            logger.error("Error saving result: %s", e)

    # Always advance the index and bump the processed counter
    return {
        "current_restaurant_idx": (state.get("current_restaurant_idx") or 0) + 1,
        "restaurants_processed": (state.get("restaurants_processed") or 0) + 1,
    }


def complete_job_node(state: CrawlerState) -> dict:
    """Finalise the job record."""
    with get_session() as session:
        job = session.query(Job).filter_by(id=state["job_id"]).first()
        if job:
            job.status = JobStatus.COMPLETED
            completed_at = datetime.now(timezone.utc)
            job.completed_at = completed_at
            if job.started_at is not None:
                job.duration_seconds = (
                    completed_at - job.started_at
                ).total_seconds()
            errors = state.get("errors")
            if errors:
                job.error_message = "\n".join(str(e) for e in errors[:20])

    downloaded = state.get("wine_lists_downloaded") or 0
    summary = (
        f"Job {state.get('job_id')} complete – "
        f"{state.get('restaurants_processed')} restaurants processed, "
        f"{downloaded} wine lists downloaded"
    )

    if downloaded > 0:
        names = state.get("wine_list_restaurant_names") or []
        if names:
            summary += f": {', '.join(sorted(names))}"

    logger.info(summary)
    return {}


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def fail_job(job_id: int, error_msg: str) -> None:
    """Mark a job as FAILED in the database."""
    try:
        with get_session() as session:
            job = session.query(Job).filter_by(id=job_id).first()
            if job and job.status == JobStatus.RUNNING:
                job.status = JobStatus.FAILED
                completed_at = datetime.now(timezone.utc)
                job.completed_at = completed_at
                job.error_message = error_msg[:2000]
                if job.started_at is not None:
                    job.duration_seconds = (
                        completed_at - job.started_at
                    ).total_seconds()
    except Exception:
        logger.exception("Could not mark job %d as failed", job_id)


def run_crawler(
    michelin_level: Optional[str] = None,
    resume_job_id: Optional[int] = None,
    force_recrawl: bool = False,
    restaurant_filter: Optional[str] = None,
    site_of_record_id: Optional[int] = None,
) -> dict:
    """
    Run the crawler workflow.

    A single Playwright browser is created here and shared across all nodes
    via the module-level ``_browser_page``.

    Parameters
    ----------
    force_recrawl:
        When *True*, re-crawl every restaurant even if a wine list was
        already found in a previous run.
    restaurant_filter:
        When set, crawl only a single restaurant.  Accepts a restaurant ID
        (numeric string) or a name (case-insensitive match).  Michelin
        listing scrape is bypassed entirely.
    site_of_record_id:
        Required for new jobs (not resume). ID of the site of record to crawl.
    """
    global _browser_page, _browser, _playwright_instance
    settings = get_settings()
    job_id: Optional[int] = None

    # Build the workflow graph
    workflow = create_crawler_workflow()

    # PostgreSQL checkpointer
    conn_str = settings.database_url.replace(
        "postgresql+psycopg://", "postgresql://"
    )

    with (
        sync_playwright() as pw,
        PostgresSaver.from_conn_string(conn_str) as checkpointer,
    ):
        checkpointer.setup()
        app = workflow.compile(checkpointer=checkpointer)

        # Launch ONE browser for the whole run
        logger.info("Launching browser (headless=%s) …", settings.headless)
        _playwright_instance = pw
        browser = pw.chromium.launch(headless=settings.headless)
        _browser = browser
        _browser_page = browser.new_page()

        try:
            # Initial state
            if resume_job_id:
                initial_state: dict = {
                    "job_id": resume_job_id,
                    "force_recrawl": force_recrawl,
                    "restaurant_filter": restaurant_filter,
                }
                job_id = resume_job_id
            else:
                initial_state = {
                    "site_of_record_id": site_of_record_id,
                    "michelin_level": michelin_level or settings.michelin_level,
                    "force_recrawl": force_recrawl,
                    "restaurant_filter": restaurant_filter,
                }

            thread_id = f"crawler_{resume_job_id or 'new'}_{datetime.now(timezone.utc).isoformat()}"
            config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

            final = None
            for output in app.stream(initial_state, config):
                final = output
                # Grab the job_id as soon as init_job produces it
                if job_id is None and isinstance(output, dict):
                    for v in output.values():
                        if isinstance(v, dict) and "job_id" in v:
                            job_id = v["job_id"]
                            break

            return final or {}

        except Exception as exc:
            if job_id:
                fail_job(job_id, str(exc))
            raise

        finally:
            _browser_page = None
            _browser = None
            _playwright_instance = None
            browser.close()

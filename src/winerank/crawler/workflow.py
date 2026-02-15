"""LangGraph workflow for restaurant crawler with PostgreSQL checkpointing."""
import logging
from datetime import datetime, timezone
from typing import TypedDict, Optional, List

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from playwright.sync_api import sync_playwright, Browser, Page

from winerank.config import get_settings
from winerank.common.db import get_session
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


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared browser context – managed by run_crawler(), used by every node
# ---------------------------------------------------------------------------
_browser_page: Optional[Page] = None


def _get_page() -> Page:
    """Return the shared Playwright Page.  Raises if not initialised."""
    if _browser_page is None:
        raise RuntimeError("Browser page not initialised – call run_crawler()")
    return _browser_page


# ---------------------------------------------------------------------------
# Workflow state
# ---------------------------------------------------------------------------

class CrawlerState(TypedDict):
    """State for crawler workflow."""
    job_id: int
    michelin_level: str
    site_of_record_id: int

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
    errors: List[str]


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
    workflow.add_node("download_wine_list", download_wine_list_node)
    workflow.add_node("extract_text", extract_text_node)
    workflow.add_node("save_result", save_result_node)
    workflow.add_node("complete_job", complete_job_node)

    # Entry
    workflow.set_entry_point("init_job")

    # Edges
    workflow.add_edge("init_job", "fetch_listing_page")
    workflow.add_edge("fetch_listing_page", "process_restaurant")

    # After processing a restaurant, decide: crawl its site or go straight
    # to save_result (e.g. no website).
    workflow.add_conditional_edges(
        "process_restaurant",
        _route_after_process,
        {
            "crawl_site": "crawl_restaurant_site",
            "save_result": "save_result",
        },
    )

    # After crawling the restaurant site, decide: download or skip to save.
    workflow.add_conditional_edges(
        "crawl_restaurant_site",
        _route_after_crawl,
        {
            "download": "download_wine_list",
            "save_result": "save_result",
        },
    )

    workflow.add_edge("download_wine_list", "extract_text")
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
    """After process_restaurant – crawl the site if it has a website."""
    restaurant = state.get("current_restaurant")
    if restaurant and restaurant.get("website_url"):
        return "crawl_site"
    return "save_result"


def _route_after_crawl(state: CrawlerState) -> str:
    """After crawl_restaurant_site – download if wine list URL was found."""
    restaurant = state.get("current_restaurant")
    if restaurant and restaurant.get("wine_list_url"):
        return "download"
    return "save_result"


def _route_after_save(state: CrawlerState) -> str:
    """After save_result – next restaurant, next page, or done."""
    idx = state["current_restaurant_idx"]
    total = len(state["restaurant_urls"])

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

        # New job
        site = session.query(SiteOfRecord).filter_by(
            site_name="Michelin Guide USA"
        ).first()
        if not site:
            site = SiteOfRecord(
                site_name="Michelin Guide USA",
                site_url="https://guide.michelin.com/us/en/selection/united-states/restaurants",
            )
            session.add(site)
            session.flush()

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
            "total_pages": 0,
            "current_page": 1,
            "restaurant_urls": [],
            "current_restaurant_idx": 0,
            "current_restaurant": None,
            "restaurants_found": 0,
            "restaurants_processed": 0,
            "wine_lists_downloaded": 0,
            "errors": [],
        }


def fetch_listing_page_node(state: CrawlerState) -> dict:
    """Fetch a Michelin listing page and extract restaurant URLs."""
    page = _get_page()
    scraper = MichelinScraper(page)
    cur_page = state["current_page"]

    try:
        url = scraper.get_listing_url(state["michelin_level"], cur_page)
        logger.info("Fetching listing page %d: %s", cur_page, url)
        result = scraper.scrape_listing_page(url)

        updates: dict = {
            "restaurant_urls": result["restaurant_urls"],
            "current_restaurant_idx": 0,
            "restaurants_found": state["restaurants_found"]
                                + len(result["restaurant_urls"]),
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
        return {"errors": state.get("errors", []) + [str(e)]}


def process_restaurant_node(state: CrawlerState) -> dict:
    """Visit a Michelin restaurant page and extract details."""
    idx = state["current_restaurant_idx"]
    urls = state["restaurant_urls"]

    if idx >= len(urls):
        return {"current_restaurant": None}

    restaurant_url = urls[idx]
    page = _get_page()
    scraper = MichelinScraper(page)

    try:
        logger.info("Processing restaurant %d/%d: %s",
                     idx + 1, len(urls), restaurant_url)
        data = scraper.scrape_restaurant_detail(restaurant_url)

        # Upsert restaurant in database
        with get_session() as session:
            existing = session.query(Restaurant).filter_by(
                michelin_url=restaurant_url
            ).first()

            if existing:
                data["id"] = existing.id
            else:
                restaurant = Restaurant(
                    name=data["name"],
                    michelin_url=data["michelin_url"],
                    website_url=data["website_url"],
                    michelin_distinction=data["michelin_distinction"],
                    city=data["city"],
                    state=data["state"],
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
        return {"current_restaurant": data}

    except Exception as e:
        logger.error("Error processing %s: %s", restaurant_url, e)
        return {
            "current_restaurant": None,
            "errors": state.get("errors", []) + [str(e)],
        }


def crawl_restaurant_site_node(state: CrawlerState) -> dict:
    """Navigate a restaurant website to locate its wine list."""
    restaurant = state["current_restaurant"]
    if not restaurant or not restaurant.get("website_url"):
        return {}

    page = _get_page()
    finder = RestaurantWineListFinder(page)

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
        )

        if wine_list_url:
            logger.info("  -> Found wine list: %s", wine_list_url)
        else:
            logger.info("  -> No wine list found")

        return {
            "current_restaurant": {**restaurant, "wine_list_url": wine_list_url},
        }

    except Exception as e:
        logger.error("Error crawling %s: %s", restaurant.get("name"), e)
        return {
            "current_restaurant": {**restaurant, "wine_list_url": None},
            "errors": state.get("errors", []) + [str(e)],
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
        downloader = WineListDownloader()
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
        return {
            "current_restaurant": merged,
            "wine_lists_downloaded": (state.get("wine_lists_downloaded") or 0) + 1,
        }

    except Exception as e:
        logger.error("Error downloading %s: %s", wine_list_url, e)
        return {"errors": (state.get("errors") or []) + [str(e)]}


def extract_text_node(state: CrawlerState) -> dict:
    """Extract structured text from the downloaded wine list."""
    restaurant = state.get("current_restaurant")
    path = restaurant.get("local_file_path") if restaurant else None
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

        merged = dict(restaurant) if restaurant else {}
        merged["text_file_path"] = text_path
        return {"current_restaurant": merged}

    except Exception as e:
        logger.error("Error extracting text from %s: %s", path, e)
        return {"errors": (state.get("errors") or []) + [str(e)]}


def save_result_node(state: CrawlerState) -> dict:
    """Persist the crawl outcome and advance the restaurant index."""
    restaurant = state.get("current_restaurant")

    if restaurant and restaurant.get("id"):
        try:
            with get_session() as session:
                rec = session.query(Restaurant).filter_by(
                    id=restaurant["id"]
                ).first()
                if rec:
                    if restaurant.get("wine_list_url"):
                        rec.crawl_status = CrawlStatus.WINE_LIST_FOUND
                        rec.wine_list_url = restaurant["wine_list_url"]
                    elif restaurant.get("website_url"):
                        rec.crawl_status = CrawlStatus.NO_WINE_LIST
                    else:
                        rec.crawl_status = CrawlStatus.NO_WEBSITE
                    rec.last_crawled_at = datetime.now(timezone.utc)

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
            job.completed_at = datetime.now(timezone.utc)
            if job.started_at and job.completed_at:
                job.duration_seconds = (
                    job.completed_at - job.started_at
                ).total_seconds()
            errors = state.get("errors")
            if errors:
                job.error_message = "\n".join(str(e) for e in errors[:20])

    logger.info(
        "Job %s complete – %s restaurants processed, %s wine lists downloaded",
        state.get("job_id"),
        state.get("restaurants_processed"),
        state.get("wine_lists_downloaded"),
    )
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
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = error_msg[:2000]
                if job.started_at and job.completed_at:
                    job.duration_seconds = (
                        job.completed_at - job.started_at
                    ).total_seconds()
    except Exception:
        logger.exception("Could not mark job %d as failed", job_id)


def run_crawler(
    michelin_level: Optional[str] = None,
    resume_job_id: Optional[int] = None,
) -> dict:
    """
    Run the crawler workflow.

    A single Playwright browser is created here and shared across all nodes
    via the module-level ``_browser_page``.
    """
    global _browser_page
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
        browser = pw.chromium.launch(headless=settings.headless)
        _browser_page = browser.new_page()

        try:
            # Initial state
            if resume_job_id:
                initial_state: dict = {"job_id": resume_job_id}
                job_id = resume_job_id
            else:
                initial_state = {
                    "michelin_level": michelin_level or settings.michelin_level,
                }

            thread_id = f"crawler_{resume_job_id or 'new'}_{datetime.now(timezone.utc).isoformat()}"
            config = {"configurable": {"thread_id": thread_id}}

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
            browser.close()

"""BinWise fallback search – find wine lists on hub.binwise.com via Google search."""

import logging
import re
import time
from typing import Optional

from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger(__name__)

# Only accept URLs from BinWise hub
BINWISE_DOMAIN = "hub.binwise.com"
BINWISE_URL_PATTERN = re.compile(
    r"https?://(?:[a-z0-9-]+\.)*" + re.escape(BINWISE_DOMAIN) + r"/[^\s]+",
    re.IGNORECASE,
)

# Stop words to ignore when matching restaurant name to page content
_STOP_WORDS = frozenset(
    {"the", "a", "an", "and", "or", "&", "restaurant", "bar", "grill", "kitchen"}
)


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _significant_words(name: str) -> list[str]:
    """Extract significant words from restaurant name (exclude stop words)."""
    normalized = _normalize_for_match(name)
    if not normalized:
        return []
    words = [w for w in normalized.split() if w and w not in _STOP_WORDS]
    return words if words else normalized.split()


def _validate_binwise_result(url: str, restaurant_name: str) -> bool:
    """Fetch the BinWise page and verify it belongs to the target restaurant.

    Uses httpx to fetch the page, then checks whether the restaurant name
    (or key words from it) appear in the page title or prominent headings.
    Returns True if the page is confirmed to be for this restaurant.
    """
    if not url or not restaurant_name or BINWISE_DOMAIN not in url.lower():
        return False

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        logger.debug("Could not fetch BinWise URL %s: %s", url, e)
        return False

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    title_text = (title_tag.get_text(strip=True) if title_tag else "") or ""
    headings = []
    for tag in soup.find_all(["h1", "h2"]):
        t = tag.get_text(strip=True)
        if t:
            headings.append(t)
    page_text = _normalize_for_match(title_text + " " + " ".join(headings))
    name_norm = _normalize_for_match(restaurant_name)
    words = _significant_words(restaurant_name)

    # Short name (1–2 significant words): require exact substring match in page text
    if len(words) <= 2:
        return name_norm in page_text if name_norm else False

    # Longer name: all significant words must appear in title/headings
    for word in words:
        if word not in page_text:
            return False
    return True


def _run_one_pass(
    restaurant_name: str,
    query: str,
    num_results: int = 5,
) -> Optional[str]:
    """Run a single Google search and return first validated hub.binwise.com URL."""
    try:
        from googlesearch import search as google_search
    except ImportError:
        logger.warning("googlesearch-python not installed – BinWise search disabled")
        return None

    try:
        results = list(google_search(query, num_results=num_results))
    except Exception as e:
        logger.debug("Google search failed for %r: %s", query, e)
        return None

    for raw_url in results:
        if not raw_url:
            continue
        # Normalize URL (strip tracking params if present)
        url = str(raw_url).split("?")[0].strip()
        if BINWISE_DOMAIN not in url.lower():
            continue
        if not BINWISE_URL_PATTERN.match(url):
            continue
        if _validate_binwise_result(url, restaurant_name):
            return url
        logger.debug("BinWise result rejected (wrong restaurant): %s", url)

    return None


def search_binwise(restaurant_name: str) -> Optional[str]:
    """Search Google for a BinWise-hosted wine list.

    Uses a two-pass strategy:
      Pass 1: site:hub.binwise.com "Restaurant Name" pdf
      Pass 2: site:hub.binwise.com "Restaurant Name"  (no pdf keyword)

    Each result is validated to confirm it belongs to the target restaurant.
    Returns the first verified hub.binwise.com URL, or None.
    """
    if not (restaurant_name or "").strip():
        return None

    name = restaurant_name.strip()
    base_query = f'site:{BINWISE_DOMAIN} "{name}"'

    try:
        # Pass 1: prefer PDF
        query_pdf = f"{base_query} pdf"
        logger.info("BinWise search pass 1 (pdf): %s", query_pdf)
        url = _run_one_pass(name, query_pdf)
        if url:
            logger.info("BinWise PDF result for %s: %s", name, url)
            return url

        # Short pause between queries
        time.sleep(2.0)

        # Pass 2: HTML / digital menu
        logger.info("BinWise search pass 2 (html): %s", base_query)
        url = _run_one_pass(name, base_query)
        if url:
            logger.info("BinWise HTML result for %s: %s", name, url)
            return url
    except Exception as e:
        logger.debug("BinWise search failed for %s: %s", name, e)
        return None

    logger.info("No validated BinWise result for %s", name)
    return None

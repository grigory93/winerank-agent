"""Michelin Guide scraper - scrape restaurant listings and detail pages."""
import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from winerank.config import get_settings
from winerank.crawler.address_parser import parse_address_with_llm
from winerank.crawler.restaurant_finder import _get_litellm_completion

logger = logging.getLogger(__name__)


def _looks_like_address(text: str) -> bool:
    """True if text looks like an address (contains comma and digits or country-like tokens)."""
    if not text or len(text) < 10:
        return False
    if "," not in text:
        return False
    if re.search(r"\d", text):
        return True
    # e.g. "Paris, France" or "Copenhagen"
    lower = text.lower()
    for token in ("usa", "france", "spain", "denmark", "mexico", "canada", "city"):
        if token in lower:
            return True
    return True  # comma present, accept


class MichelinScraper:
    """Scraper for Michelin Guide website."""

    BASE_URL = "https://guide.michelin.com/us/en/selection/united-states/restaurants"

    DISTINCTION_SLUGS = {
        "3": "3-stars-michelin",
        "2": "2-stars-michelin",
        "1": "1-star-michelin",
        "gourmand": "bib-gourmand",
        "selected": "the-plate-michelin",
        "all": "",
    }

    # Mapping: US state slug in URL -> human-readable name
    STATE_MAP = {
        "district-of-columbia": "DC",
        "new-york": "New York",
        "california": "California",
        "illinois": "Illinois",
        "colorado": "Colorado",
        "pennsylvania": "Pennsylvania",
        "florida": "Florida",
        "texas": "Texas",
        "massachusetts": "Massachusetts",
        "washington": "Washington",
        "oregon": "Oregon",
        "virginia": "Virginia",
        "georgia": "Georgia",
        "connecticut": "Connecticut",
        "hawaii": "Hawaii",
        "louisiana": "Louisiana",
        "nevada": "Nevada",
        "ohio": "Ohio",
        "michigan": "Michigan",
        "minnesota": "Minnesota",
        "missouri": "Missouri",
        "new-jersey": "New Jersey",
        "north-carolina": "North Carolina",
        "south-carolina": "South Carolina",
        "tennessee": "Tennessee",
        "arizona": "Arizona",
    }

    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base_url = base_url.rstrip("/")
        self.settings = get_settings()

    # -----------------------------------------------------------------
    # URL helpers
    # -----------------------------------------------------------------

    def get_listing_url(self, michelin_level: str, page_num: int = 1) -> str:
        slug = self.DISTINCTION_SLUGS.get(michelin_level.lower(), "3-stars-michelin")
        url = f"{self.base_url}/{slug}" if slug else self.base_url
        if page_num > 1:
            url = f"{url}/page/{page_num}"
        return url

    # -----------------------------------------------------------------
    # Listing page
    # -----------------------------------------------------------------

    def scrape_listing_page(self, url: str) -> dict:
        """Return ``{restaurant_urls, total_restaurants, total_pages}``."""
        try:
            logger.info("Navigating to %s (timeout=%dms)", url, self.settings.browser_timeout)
            logger.info("Browser page state: closed=%s", self.page.is_closed())

            self.page.goto(url, timeout=self.settings.browser_timeout)
            self.page.wait_for_load_state("domcontentloaded")
            
            # Wait briefly for JS to populate the results
            self.page.wait_for_timeout(2000)

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Find the main results container (not promotional/nearby sections)
            # The actual filtered results are in js-restaurant__list_items
            results_container = soup.find("div", class_="js-restaurant__list_items")

            restaurant_urls: list[str] = []

            if not results_container or not isinstance(results_container, Tag):
                logger.warning("Could not find main results container on %s", url)
                return {
                    "restaurant_urls": [],
                    "total_restaurants": 0,
                    "total_pages": 0,
                }

            # Extract restaurant cards from the main results container only
            cards = results_container.find_all("div", class_="js-restaurant__list_item")
            
            for card in cards:
                # Extract the restaurant URL from the card's title link
                title = card.find("h3", class_="card__menu-content--title")
                if not title:
                    continue
                
                link = title.find("a", href=True)
                if not link or "/restaurant/" not in link.get("href", ""):
                    continue
                
                full_url = urljoin("https://guide.michelin.com", link["href"])
                restaurant_urls.append(full_url)

            # Try to extract total count
            total_restaurants = 0
            total_pages = 1
            text_content = soup.get_text()
            m = re.search(r"of\s+([\d,]+)\s+restaurants?", text_content, re.I)
            if m:
                total_restaurants = int(m.group(1).replace(",", ""))
                total_pages = max(1, (total_restaurants + 47) // 48)

            logger.info(
                "Listing page %s -> %d restaurants, %d total, %d pages",
                url, len(restaurant_urls), total_restaurants, total_pages,
            )
            return {
                "restaurant_urls": restaurant_urls,
                "total_restaurants": total_restaurants,
                "total_pages": total_pages,
            }

        except PlaywrightTimeout:
            raise Exception(f"Timeout loading listing page {url}")
        except Exception as e:
            page_closed = self.page.is_closed() if hasattr(self.page, "is_closed") else "unknown"
            logger.error(
                "Scraping error: type=%s page_closed=%s url=%s detail=%s",
                type(e).__name__, page_closed, url, e,
            )
            raise Exception(f"Error scraping listing page {url}: {e}")

    # -----------------------------------------------------------------
    # Restaurant detail page
    # -----------------------------------------------------------------

    def scrape_restaurant_detail(self, url: str) -> dict:
        """Scrape a single restaurant page on the Michelin Guide."""
        try:
            self.page.goto(url, timeout=self.settings.browser_timeout)
            self.page.wait_for_load_state("networkidle")

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # -- name --
            h1 = soup.find("h1")
            name = h1.get_text(strip=True) if h1 else "Unknown"

            # -- website URL --
            website_url = self._extract_website_url(soup)

            # -- distinction --
            distinction = self._extract_distinction(soup)

            # -- location from address block on page + LLM parsing --
            address_block = self._extract_address_block(soup)
            street_address: Optional[str] = None
            zip_code: Optional[str] = None
            if address_block:
                parts = parse_address_with_llm(
                    address_block,
                    llm_fn=_get_litellm_completion(),
                    api_key=self.settings.llm_api_key or None,
                    model=f"{self.settings.llm_provider}/{self.settings.llm_model}",
                    temperature=self.settings.llm_temperature,
                    max_tokens=200,
                )
                street_address = parts.address
                city = parts.city
                state = parts.state
                zip_code = parts.zip
                country = parts.country
            else:
                city, state = self._extract_location_fallback(url)
                country = None
            # Workflow may override country from site name

            # -- cuisine --
            cuisine = self._extract_cuisine(soup)

            # -- price range --
            price_range = self._extract_price(soup)

            return {
                "name": name,
                "michelin_url": url,
                "website_url": website_url,
                "michelin_distinction": distinction,
                "address": street_address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
                "country": country,
                "cuisine": cuisine,
                "price_range": price_range,
            }

        except PlaywrightTimeout:
            raise Exception(f"Timeout loading restaurant page {url}")
        except Exception as e:
            raise Exception(f"Error scraping restaurant page {url}: {e}")

    # -----------------------------------------------------------------
    # Extraction helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _extract_website_url(soup: BeautifulSoup) -> Optional[str]:
        """Look for the restaurant's own website link."""
        # First: explicit "Visit Website" text
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if "Visit Website" in text:
                href = a["href"]
                if href.startswith("http") and "guide.michelin.com" not in href:
                    return href

        # Fallback: any external link whose text suggests a website
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("http"):
                continue
            if "guide.michelin.com" in href:
                continue
            if href.startswith("tel:") or href.startswith("mailto:"):
                continue
            text = a.get_text(strip=True).lower()
            if any(kw in text for kw in ("website", "visit", "www", "home")):
                return href

        return None

    @staticmethod
    def _extract_distinction(soup: BeautifulSoup) -> str:
        """Determine Michelin distinction from page text."""
        text = soup.get_text().lower()
        if "three michelin stars" in text or "3 stars" in text or "three stars" in text:
            return "3-stars"
        if "two michelin stars" in text or "2 stars" in text or "two stars" in text:
            return "2-stars"
        if "one michelin star" in text or "1 star" in text or "one star" in text:
            return "1-star"
        if "bib gourmand" in text:
            return "bib-gourmand"
        return "selected"

    @staticmethod
    def _extract_address_block(soup: BeautifulSoup) -> Optional[str]:
        """
        Extract the address block from the restaurant detail page.

        Looks for content under the restaurant name (h1) and above price/cuisine:
        elements with address-like class names, or the first text block that
        looks like an address (commas, numbers).
        """
        # Prefer explicit address/location container
        for attr in ("class", "data-testid"):
            for elem in soup.find_all(attrs={attr: True}):
                val = elem.get(attr)
                if isinstance(val, list):
                    val = " ".join(val)
                if val and ("address" in val.lower() or "location" in val.lower()):
                    text = elem.get_text(separator=" ", strip=True)
                    if text and len(text) < 300 and _looks_like_address(text):
                        return text

        # Fallback: after h1, take first block that looks like an address
        h1 = soup.find("h1")
        if not h1:
            return None
        for sibling in h1.find_next_siblings():
            text = sibling.get_text(separator=" ", strip=True)
            if not text or len(text) > 250:
                continue
            if "$" in text or "Cuisine" in text or "Visit Website" in text:
                break
            if _looks_like_address(text):
                return text
        return None

    @classmethod
    def _extract_location_fallback(cls, url: str) -> tuple[Optional[str], Optional[str]]:
        """Derive city/state from the Michelin URL path segments when no address block."""
        parts = url.rstrip("/").split("/")
        try:
            ri = parts.index("restaurant")
        except ValueError:
            return None, None

        city_raw = parts[ri - 1] if ri >= 1 else None
        state_raw = parts[ri - 2] if ri >= 2 else None

        city = None
        if city_raw:
            city = re.sub(r"[_-]\d+$", "", city_raw)
            city = city.replace("-", " ").replace("_", " ").title()

        state = None
        if state_raw:
            state = cls.STATE_MAP.get(state_raw, state_raw.replace("-", " ").title())

        return city, state

    @staticmethod
    def _extract_cuisine(soup: BeautifulSoup) -> Optional[str]:
        """Try to pull a short cuisine label from the page."""
        for elem in soup.find_all(["span", "div", "p"]):
            text = elem.get_text(strip=True)
            lower = text.lower()
            if "cuisine" in lower and len(text) < 60:
                return text
        return None

    @staticmethod
    def _extract_price(soup: BeautifulSoup) -> Optional[str]:
        """Find the longest $ string on the page."""
        text = soup.get_text()
        m = re.findall(r"\${1,4}", text)
        if m:
            return max(m, key=len)
        return None

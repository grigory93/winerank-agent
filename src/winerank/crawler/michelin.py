"""Michelin Guide scraper - scrape restaurant listings and detail pages."""
import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from winerank.config import get_settings

logger = logging.getLogger(__name__)


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

    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()

    # -----------------------------------------------------------------
    # URL helpers
    # -----------------------------------------------------------------

    def get_listing_url(self, michelin_level: str, page_num: int = 1) -> str:
        slug = self.DISTINCTION_SLUGS.get(michelin_level.lower(), "3-stars-michelin")
        url = f"{self.BASE_URL}/{slug}" if slug else self.BASE_URL
        if page_num > 1:
            url = f"{url}/page/{page_num}"
        return url

    # -----------------------------------------------------------------
    # Listing page
    # -----------------------------------------------------------------

    def scrape_listing_page(self, url: str) -> dict:
        """Return ``{restaurant_urls, total_restaurants, total_pages}``."""
        try:
            self.page.goto(url, timeout=self.settings.browser_timeout)
            self.page.wait_for_load_state("networkidle")

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Collect all unique /restaurant/ links
            seen: set[str] = set()
            restaurant_urls: list[str] = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/restaurant/" not in href:
                    continue
                full = urljoin("https://guide.michelin.com", href)
                if full not in seen:
                    seen.add(full)
                    restaurant_urls.append(full)

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

            # -- location from URL --
            city, state = self._extract_location(url)

            # -- cuisine --
            cuisine = self._extract_cuisine(soup)

            # -- price range --
            price_range = self._extract_price(soup)

            return {
                "name": name,
                "michelin_url": url,
                "website_url": website_url,
                "michelin_distinction": distinction,
                "city": city,
                "state": state,
                "country": "USA",
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
                if href.startswith("http"):
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

    @classmethod
    def _extract_location(cls, url: str) -> tuple[Optional[str], Optional[str]]:
        """Derive city/state from the Michelin URL path segments."""
        parts = url.rstrip("/").split("/")
        # Typical: …/us/en/{state}/{city}/restaurant/{slug}
        # Find the index of "restaurant" and work backwards
        try:
            ri = parts.index("restaurant")
        except ValueError:
            return None, None

        city_raw = parts[ri - 1] if ri >= 1 else None
        state_raw = parts[ri - 2] if ri >= 2 else None

        city = None
        if city_raw:
            city = re.sub(r"[_-]\d+$", "", city_raw)     # strip numeric suffix
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

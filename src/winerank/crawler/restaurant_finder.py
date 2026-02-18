"""Restaurant website wine list finder – navigate restaurant sites to find wine lists.

Uses a three-tier approach:
  Tier 1  Cached URL – verify a previously-known wine list URL.
  Tier 2  Smart keyword search – enhanced keyword matching with *link-context*
          analysis (inspects text surrounding each link, not just the link text).
  Tier 3  LLM-guided search – ask the LLM which links to follow, using a
          compact page summary to stay economical with tokens.

Keyword lists are derived from analysis of 14+ Michelin-starred restaurant
websites including Per Se, French Laundry, Le Bernardin, Jungsik, Eleven
Madison Park, Atelier Crenn, Smyth, Quince, Addison, Providence, Benu,
Somni, and The Inn at Little Washington.
"""

import json
import logging
import re
import unicodedata
from typing import Optional, Set
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from winerank.config import get_settings

logger = logging.getLogger(__name__)

# Lazy-loaded – import only when first needed
_litellm_completion = None


def _get_litellm_completion():
    """Return litellm.completion, or None if unavailable."""
    global _litellm_completion
    if _litellm_completion is not None:
        return _litellm_completion
    try:
        from litellm import completion
        _litellm_completion = completion
        return completion
    except ImportError:
        logger.warning("litellm not installed – LLM navigation disabled")
        return None


# -----------------------------------------------------------------------
# URL patterns to skip (never useful for wine list discovery)
# -----------------------------------------------------------------------
_SKIP_RE = re.compile(
    r"(?:instagram|facebook|twitter|youtube|linkedin|tiktok|yelp|tripadvisor"
    r"|opentable|resy|sevenrooms)\.com"
    r"|mailto:|tel:|javascript:|#$"
    r"|/careers|/jobs|/press(?:/|$)|/privacy|/terms|/legal|/cookie"
    r"|/accessibility|/reservations?(?:/|$)|/booking|/gift.?card"
    r"|/shop(?:/|$)|/contact(?:/|$)|/login|/signup|/account"
    r"|/events(?:/|$)|/private.?dining",
    re.IGNORECASE,
)

# -----------------------------------------------------------------------
# Known external wine list hosting platforms
# -----------------------------------------------------------------------
_WINE_PLATFORM_RE = re.compile(
    r"hub\.binwise\.com"
    r"|bw-winelist"
    r"|binwise\.com/restaurant"
    r"|starwinelist\.com"
    r"|enowine\.com"
    r"|wineby\.com",
    re.IGNORECASE,
)


class RestaurantWineListFinder:
    """Find wine lists on restaurant websites using tiered search strategies.

    Public attributes after ``find_wine_list()`` returns:
        pages_loaded  – number of page navigations performed
        tokens_used   – total LLM tokens consumed (0 if LLM was not used)
    """

    # ------------------------------------------------------------------
    # Keyword lists  (ordered by specificity – highest first)
    # Derived from real Michelin restaurant website analysis.
    # ------------------------------------------------------------------

    # Primary: wine-specific terms
    WINE_KEYWORDS: list[str] = [
        # Very specific – direct wine list references
        "wine list",
        "wine selections",
        "wine selection",
        "wine & cocktail selections",
        "wine & cocktails",
        "wine & spirits",
        "wine cocktail selections",
        "wine spirits",
        "wine program",
        "wine menu",
        "wine pairing",
        "wine dinner",
        "wine club",
        # Moderately specific
        "wine",
        "cellar",
        "sommelier",
        "by the glass",
        # Beverage-related
        "beverage program",
        "beverage menu",
        "beverage",
        "bar menu",
        "cocktail menu",
        "cocktail list",
        "cocktail selections",
        "spirits selections",
        "spirits",
        "drinks menu",
        "drinks list",
        "drink menu",
        "drink",
    ]

    # Secondary: broader navigation terms that may lead to wine content
    MENU_KEYWORDS: list[str] = [
        "menus & stories",
        "menus",
        "menu",
        "dine",
        "dining",
        "food & drink",
        "food and drink",
        "food & beverage",
        "the experience",
        "our menu",
        "daily menus",
        # Dining formats common at fine-dining / Michelin restaurants
        "chef's counter",
        "chefs counter",
        "chef's table",
        "chefs table",
        "tasting menu",
        "tasting",
        "bar tasting",
        "omakase",
        "prix fixe",
        "prix-fixe",
        # FAQ pages frequently contain wine list links or policies
        "faq",
        "faqs",
        "frequently asked questions",
    ]

    # Tertiary: general informational pages that occasionally contain wine
    # list links.  Scored lowest – only followed when no better candidate
    # exists at the current depth.
    INFORMATIONAL_KEYWORDS: list[str] = [
        "about",
        "about us",
        "the restaurant",
        "our story",
        "guest information",
        "information",
        "visit",
        "plan your visit",
        "philosophy",
    ]

    # Phrases in *surrounding text* that signal a nearby link is a wine list
    _CONTEXT_PHRASES: list[str] = [
        "wine list",
        "wine menu",
        "wine selection",
        "wine program",
        "beverage program",
        "beverage list",
        "available here",
        "download",
        "view our",
        "see our",
        "current version",
    ]

    # Wine-related terms for PDF scoring
    _PDF_WINE_TERMS: list[str] = [
        "wine", "vino", "cellar", "sommelier", "beverage",
        "spirits", "cocktail", "by-the-glass", "btg",
    ]

    # ------------------------------------------------------------------
    # French (fr) keyword and phrase lists – merged when language_hint is "fr"
    # ------------------------------------------------------------------
    WINE_KEYWORDS_FR: list[str] = [
        "carte des vins", "liste des vins", "vins", "cave", "sommelier",
        "boissons", "menu des vins", "carte des boissons", "cocktails",
        "spiritueux", "vin", "carte du vin",
    ]
    MENU_KEYWORDS_FR: list[str] = [
        "menus", "menu", "notre carte", "dégustation", "à propos", "nous",
        "faq", "informations", "la carte", "restaurant", "dining",
    ]
    INFORMATIONAL_KEYWORDS_FR: list[str] = [
        "à propos", "nous", "informations", "visite", "histoire", "philosophie",
    ]
    _CONTEXT_PHRASES_FR: list[str] = [
        "carte des vins", "liste des vins", "disponible", "télécharger",
        "voir notre", "version actuelle", "voir la carte",
    ]
    _PDF_WINE_TERMS_FR: list[str] = [
        "vin", "vins", "cave", "boissons", "sommelier", "carte",
    ]

    # ------------------------------------------------------------------
    # Spanish (es) keyword and phrase lists – merged when language_hint is "es"
    # ------------------------------------------------------------------
    WINE_KEYWORDS_ES: list[str] = [
        "carta de vinos", "lista de vinos", "vinos", "bodega", "sommelier",
        "bebidas", "carta de bebidas", "menu de vinos", "cocktails",
        "licores", "vino",
    ]
    MENU_KEYWORDS_ES: list[str] = [
        "menús", "menú", "nuestra carta", "degustación", "sobre nosotros",
        "faq", "información", "la carta", "restaurante", "comer",
    ]
    INFORMATIONAL_KEYWORDS_ES: list[str] = [
        "sobre nosotros", "nosotros", "información", "visita", "historia", "filosofía",
    ]
    _CONTEXT_PHRASES_ES: list[str] = [
        "carta de vinos", "lista de vinos", "disponible", "descargar",
        "ver nuestra", "versión actual", "ver la carta",
    ]
    _PDF_WINE_TERMS_ES: list[str] = [
        "vino", "vinos", "bodega", "bebidas", "sommelier", "carta",
    ]

    @staticmethod
    def _normalize_text(s: str) -> str:
        """Lowercase and normalize accents for consistent keyword matching."""
        if not s:
            return ""
        s = s.lower().strip()
        nfd = unicodedata.normalize("NFD", s)
        return "".join(c for c in nfd if unicodedata.category(c) != "Mn")

    def _build_norm_lists(self) -> None:
        """Pre-normalize all effective keyword lists for use in scoring hot paths."""
        n = self._normalize_text
        self._norm_wine_keywords:   list[str] = [n(kw) for kw in self._effective_wine_keywords]
        self._norm_menu_keywords:   list[str] = [n(kw) for kw in self._effective_menu_keywords]
        self._norm_info_keywords:   list[str] = [n(kw) for kw in self._effective_informational_keywords]
        self._norm_context_phrases: list[str] = [n(ph) for ph in self._effective_context_phrases]
        self._norm_pdf_wine_terms:  list[str] = [n(t)  for t  in self._effective_pdf_wine_terms]

    def __init__(self, page: Page):
        self.page = page
        self.settings = get_settings()
        self.visited_urls: Set[str] = set()
        self.pages_loaded: int = 0
        self.tokens_used: int = 0
        self._language_hint: str = "en"
        # Effective keyword lists default to English; overridden in find_wine_list.
        self._effective_wine_keywords: list[str] = self.WINE_KEYWORDS
        self._effective_menu_keywords: list[str] = self.MENU_KEYWORDS
        self._effective_informational_keywords: list[str] = self.INFORMATIONAL_KEYWORDS
        self._effective_context_phrases: list[str] = self._CONTEXT_PHRASES
        self._effective_pdf_wine_terms: list[str] = self._PDF_WINE_TERMS
        self._build_norm_lists()

    # ==================================================================
    # Public API
    # ==================================================================

    def find_wine_list(
        self,
        restaurant_url: str,
        cached_wine_list_url: Optional[str] = None,
        language_hint: Optional[str] = None,
    ) -> Optional[str]:
        """Return the URL of a wine list (PDF or page), or ``None``."""
        self.visited_urls.clear()
        self.pages_loaded = 0
        self.tokens_used = 0

        # Set effective keyword lists from language hint (fr/es → merge with EN).
        # Pre-normalized lists are built once via _build_norm_lists to avoid repeated
        # normalize calls inside the hot scoring loops.
        hint = (language_hint or "").strip().lower()
        if hint == "fr":
            raw_wine = self.WINE_KEYWORDS + self.WINE_KEYWORDS_FR
            raw_menu = self.MENU_KEYWORDS + self.MENU_KEYWORDS_FR
            raw_info = self.INFORMATIONAL_KEYWORDS + self.INFORMATIONAL_KEYWORDS_FR
            raw_ctx  = self._CONTEXT_PHRASES + self._CONTEXT_PHRASES_FR
            raw_pdf  = self._PDF_WINE_TERMS + self._PDF_WINE_TERMS_FR
        elif hint == "es":
            raw_wine = self.WINE_KEYWORDS + self.WINE_KEYWORDS_ES
            raw_menu = self.MENU_KEYWORDS + self.MENU_KEYWORDS_ES
            raw_info = self.INFORMATIONAL_KEYWORDS + self.INFORMATIONAL_KEYWORDS_ES
            raw_ctx  = self._CONTEXT_PHRASES + self._CONTEXT_PHRASES_ES
            raw_pdf  = self._PDF_WINE_TERMS + self._PDF_WINE_TERMS_ES
        else:
            raw_wine = self.WINE_KEYWORDS
            raw_menu = self.MENU_KEYWORDS
            raw_info = self.INFORMATIONAL_KEYWORDS
            raw_ctx  = self._CONTEXT_PHRASES
            raw_pdf  = self._PDF_WINE_TERMS

        self._effective_wine_keywords = raw_wine
        self._effective_menu_keywords = raw_menu
        self._effective_informational_keywords = raw_info
        self._effective_context_phrases = raw_ctx
        self._effective_pdf_wine_terms = raw_pdf
        self._build_norm_lists()

        self._language_hint = hint or "en"

        # ---- Tier 1: previously-known URL ----
        if cached_wine_list_url:
            logger.info("  Tier 1: verifying cached URL %s", cached_wine_list_url)
            if self._verify_url(cached_wine_list_url):
                return cached_wine_list_url

        # ---- Tier 2: smart keyword search (wine → menu fallback) ----
        logger.info("  Tier 2: smart keyword search")
        url = self._smart_search(
            restaurant_url,
            max_depth=self.settings.restaurant_website_depth,
        )
        if url:
            return url

        # ---- Tier 3: LLM-guided search ----
        llm_fn = _get_litellm_completion()
        if self.settings.use_llm_navigation and llm_fn and self.settings.llm_api_key:
            logger.info("  Tier 3: LLM-guided search")
            url = self._llm_guided_search(
                restaurant_url, llm_fn, max_pages=4, language_hint=self._language_hint
            )
            if url:
                return url

        return None

    # ==================================================================
    # Tier 2 – Smart keyword search with context analysis
    # ==================================================================

    def _smart_search(
        self,
        url: str,
        max_depth: int,
        current_depth: int = 0,
    ) -> Optional[str]:
        """Keyword-based search enhanced with link-context analysis.

        After loading each page the method performs three passes:
          1. Look for wine-related PDF links (both internal *and* external).
          2. Look for high-confidence *external* wine links (known platforms,
             external PDFs, external links with strong wine keywords).
          3. Score internal links and recurse into them.
        """
        if current_depth >= max_depth:
            return None
        if self.pages_loaded >= self.settings.max_restaurant_pages:
            return None

        url = self._normalize_url(url)
        if url in self.visited_urls:
            return None
        self.visited_urls.add(url)

        try:
            self.page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            # Brief wait for JS-rendered content
            self.page.wait_for_timeout(1500)
            self.pages_loaded += 1

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")
            base_domain = self._get_domain(url)

            # Pass 1 – wine-related PDF links (checks ALL links incl. external)
            pdf_url = self._find_best_pdf(soup, url, base_domain)
            if pdf_url:
                logger.info("    Found wine-related PDF: %s", pdf_url)
                return pdf_url

            # Pass 2 – external wine links (platforms, external PDFs, strong
            #          wine keyword matches on other domains)
            ext_wine = self._find_external_wine_links(soup, url, base_domain)
            for _score, ext_url, _text in ext_wine:
                result = self._check_external_page(ext_url)
                if result:
                    return result

            # Pass 3 – score internal links (wine keywords + context)
            scored = self._score_all_links(soup, url, base_domain)
            scored.sort(reverse=True, key=lambda x: x[0])

            if scored:
                logger.debug(
                    "    Top links: %s",
                    [(s, t[:40]) for s, _, t in scored[:5]],
                )

            # Follow the best internal links recursively
            for _score, link_url, _text in scored:
                result = self._smart_search(link_url, max_depth, current_depth + 1)
                if result:
                    return result

            return None

        except PlaywrightTimeout:
            logger.debug("    Timeout loading %s", url)
            return None
        except Exception as exc:
            logger.debug("    Error loading %s: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # External wine link discovery & checking
    # ------------------------------------------------------------------

    def _find_external_wine_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
    ) -> list[tuple[int, str, str]]:
        """Find external links likely to be wine list resources.

        Returns ``(score, url, text)`` sorted by score descending.  Only
        links on *other* domains are considered; same-domain links are
        handled by ``_score_all_links``.
        """
        results: list[tuple[int, str, str]] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)
            link_domain = self._get_domain(abs_url)

            # Only external links
            if link_domain == base_domain or not link_domain:
                continue
            if _SKIP_RE.search(abs_url):
                continue
            norm = self._normalize_url(abs_url)
            if norm in self.visited_urls:
                continue

            text = a.get_text(strip=True).lower()
            context = self._get_link_context(a)

            # --- Check 1: known wine list platform ---
            if self._is_wine_platform_url(abs_url):
                results.append((1000, abs_url, text))
                continue

            # --- Check 2: external PDF with wine relevance ---
            if self._is_pdf_url(abs_url):
                pdf_score = self._score_pdf(abs_url, a)
                if pdf_score > 0:
                    results.append((500 + pdf_score, abs_url, text))
                    continue
                # Accept any PDF found in wine-navigation context
                context_norm = self._normalize_text(context)
                for phrase_norm in self._norm_context_phrases:
                    if phrase_norm in context_norm:
                        results.append((400, abs_url, text))
                        break
                else:
                    # PDF with no wine signal -- low priority but still viable
                    results.append((100, abs_url, text))
                continue

            # --- Check 3: context phrases in surrounding text ---
            # A generic link like "here" is very strong signal when the
            # surrounding text says "wine list is available here".
            wine_score = self._score_wine_keywords_only(text, href)
            context_norm = self._normalize_text(context)
            context_hits = sum(
                1 for phrase_norm in self._norm_context_phrases
                if phrase_norm in context_norm
            )
            if context_hits:
                results.append((300 + wine_score + context_hits * 50,
                                abs_url, text))
                continue

            # --- Check 4: strong wine keywords in link text / href ---
            if wine_score >= 50:
                results.append((wine_score, abs_url, text))

        results.sort(reverse=True, key=lambda x: x[0])
        return results

    def _check_external_page(self, url: str) -> Optional[str]:
        """Follow an external link *one level* looking for wine list content.

        Returns a wine list URL if found, otherwise ``None``.  Does NOT
        recurse further into external domains.
        """
        # Direct PDF -- return immediately without loading
        if self._is_pdf_url(url):
            logger.info("    Found external wine PDF: %s", url)
            return url

        # Known wine platform -- return the URL as the wine list itself
        if self._is_wine_platform_url(url):
            logger.info("    Found wine platform URL: %s", url)
            return url

        # Download-style URLs in a wine context – return directly;
        # Playwright can't capture file downloads as page content.
        path_lower = unquote(urlparse(url).path).lower()
        url_lower = url.lower()
        if "/download" in path_lower and any(
            t in url_lower
            for t in ("wine", "beverage", "cellar", "sommelier", "list")
        ):
            logger.info("    Found wine download URL: %s", url)
            return url

        # Load the page and look for PDFs / platform links on it
        norm = self._normalize_url(url)
        if norm in self.visited_urls:
            return None
        if self.pages_loaded >= self.settings.max_restaurant_pages:
            return None

        self.visited_urls.add(norm)
        try:
            self.page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            self.page.wait_for_timeout(2000)
            self.pages_loaded += 1

            html = self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Check for wine-related PDFs on the external page
            pdf_url = self._find_best_pdf(
                soup, url, self._get_domain(url),
            )
            if pdf_url:
                logger.info("    Found PDF on external page: %s", pdf_url)
                return pdf_url

            # Check for further wine platform links
            for a in soup.find_all("a", href=True):
                link = urljoin(url, a.get("href", ""))
                if self._is_pdf_url(link):
                    score = self._score_pdf(link, a)
                    if score > 0:
                        logger.info("    Found PDF on external page: %s", link)
                        return link
                if self._is_wine_platform_url(link):
                    logger.info("    Found wine platform link: %s", link)
                    return link

            return None
        except PlaywrightTimeout:
            logger.debug("    Timeout loading external %s", url)
            return None
        except Exception as exc:
            logger.debug("    Error loading external %s: %s", url, exc)
            return None

    def _score_wine_keywords_only(self, text: str, href: str) -> int:
        """Score a link using *only* wine keywords (not menu keywords).

        Used for external link filtering where we need higher confidence.
        """
        score = 0
        text_norm = self._normalize_text(text)
        href_norm = self._normalize_text(unquote(href))
        nwk = self._norm_wine_keywords
        n = len(nwk)

        for rank, kw_norm in enumerate(nwk):
            weight = n - rank
            if kw_norm == text_norm:
                score += weight * 10
            elif kw_norm in text_norm:
                score += weight * 5
            slug = kw_norm.replace(" ", "-")
            if slug in href_norm:
                score += weight * 3

        return score

    @staticmethod
    def _is_wine_platform_url(url: str) -> bool:
        """Check whether *url* belongs to a known wine-list hosting platform."""
        return bool(_WINE_PLATFORM_RE.search(url))

    # ------------------------------------------------------------------
    # PDF detection & scoring
    # ------------------------------------------------------------------

    def _find_best_pdf(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
    ) -> Optional[str]:
        """Find the most wine-relevant PDF link on the page."""
        candidates: list[tuple[int, str]] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)
            if not self._is_pdf_url(abs_url):
                continue

            score = self._score_pdf(abs_url, a)
            candidates.append((score, abs_url))

        if not candidates:
            return None

        # Sort by score descending, return best if it scores above threshold
        candidates.sort(reverse=True, key=lambda x: x[0])
        best_score, best_url = candidates[0]

        # Require at least *some* wine signal (score > 0 means wine term found)
        if best_score > 0:
            return best_url

        # If we reached this page via wine/menu navigation, accept any PDF
        # (the navigation itself is the context signal)
        return best_url

    def _score_pdf(self, url: str, tag: Tag) -> int:
        """Score a PDF link by how likely it is to be a wine list."""
        score = 0
        path = self._normalize_text(unquote(urlparse(url).path))
        text = self._normalize_text(tag.get_text(strip=True))
        context = self._normalize_text(self._get_link_context(tag))

        for t_norm in self._norm_pdf_wine_terms:
            if t_norm in path:
                score += 10
            if t_norm in text:
                score += 10
            if t_norm in context:
                score += 5

        # Penalise likely non-wine PDFs
        non_wine = ["catering", "press", "event", "private-dining", "buyout", "resume"]
        for nw in non_wine:
            if nw in path or nw in text:
                score -= 20

        return score

    @staticmethod
    def _is_pdf_url(url: str) -> bool:
        """Check if URL points to a PDF, handling URL-encoded suffixes."""
        path = unquote(urlparse(url).path).lower().strip()
        return path.endswith(".pdf")

    # ------------------------------------------------------------------
    # Link scoring  (keywords + surrounding-text context)
    # ------------------------------------------------------------------

    def _score_all_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
    ) -> list[tuple[int, str, str]]:
        """Score every internal link on the page.  Returns ``(score, url, text)``."""
        results: list[tuple[int, str, str]] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)

            # Skip external, visited, anchor-only, and irrelevant links
            if self._get_domain(abs_url) != base_domain:
                continue
            if _SKIP_RE.search(abs_url):
                continue
            norm = self._normalize_url(abs_url)
            if norm in self.visited_urls:
                continue

            text = a.get_text(strip=True)
            context = self._get_link_context(a)

            score = self._score_link(text, href, context)
            if score > 0:
                results.append((score, abs_url, text))

        return results

    def _score_link(self, text: str, href: str, context: str) -> int:
        """Score a single link using wine, menu, and informational keywords."""
        score = 0
        text_norm = self._normalize_text(text)
        href_norm = self._normalize_text(unquote(href))
        context_norm = self._normalize_text(context)

        # --- Wine keywords (high weight) ---
        nwk = self._norm_wine_keywords
        n = len(nwk)
        for rank, kw_norm in enumerate(nwk):
            weight = n - rank
            if kw_norm == text_norm:
                score += weight * 10       # exact match on link text
            elif kw_norm in text_norm:
                score += weight * 5        # partial match on link text
            slug = kw_norm.replace(" ", "-")
            if slug in href_norm:
                score += weight * 3        # match in URL path

        # --- Menu keywords (lower weight, only if no wine hit yet) ---
        if score == 0:
            nmk = self._norm_menu_keywords
            m = len(nmk)
            for rank, kw_norm in enumerate(nmk):
                weight = m - rank
                if kw_norm == text_norm:
                    score += weight * 3
                elif kw_norm in text_norm:
                    score += weight * 2
                slug = kw_norm.replace(" ", "-")
                if slug in href_norm:
                    score += weight * 1

        # --- Informational keywords (lowest weight – last resort) ---
        if score == 0:
            nik = self._norm_info_keywords
            k = len(nik)
            for rank, kw_norm in enumerate(nik):
                weight = k - rank
                if kw_norm == text_norm:
                    score += weight * 1
                elif kw_norm in text_norm:
                    score += weight * 1
                slug = kw_norm.replace(" ", "-")
                if slug in href_norm:
                    score += weight * 1

        # --- Context analysis: text surrounding the link ---
        for phrase_norm in self._norm_context_phrases:
            if phrase_norm in context_norm:
                score += 25                # strong signal: nearby text mentions wine

        return score

    @staticmethod
    def _get_link_context(tag: Tag, max_chars: int = 300) -> str:
        """Return lowercased text of the nearest block-level parent element."""
        for parent in tag.parents:
            if parent.name in ("p", "div", "li", "section", "article", "span"):
                return parent.get_text(strip=True).lower()[:max_chars]
        return ""

    # ==================================================================
    # Tier 3 – LLM-guided search
    # ==================================================================

    def _llm_guided_search(
        self,
        start_url: str,
        llm_fn,
        max_pages: int = 4,
        language_hint: str = "en",
    ) -> Optional[str]:
        """Use LLM to decide which links to follow.  Economical: max 2 calls."""
        pages_explored = 0
        urls_to_explore = [start_url]

        while urls_to_explore and pages_explored < max_pages:
            url = urls_to_explore.pop(0)
            url = self._normalize_url(url)
            if url in self.visited_urls:
                continue

            try:
                self.page.goto(
                    url,
                    timeout=self.settings.browser_timeout,
                    wait_until="domcontentloaded",
                )
                self.page.wait_for_timeout(1500)
                self.pages_loaded += 1
                self.visited_urls.add(url)
                pages_explored += 1

                html = self.page.content()
                soup = BeautifulSoup(html, "html.parser")
                base_domain = self._get_domain(url)

                # Quick check: any wine-related PDFs here?
                pdf_url = self._find_best_pdf(soup, url, base_domain)
                if pdf_url:
                    logger.info("    LLM path: found PDF %s", pdf_url)
                    return pdf_url

                # Build compact page summary for LLM
                nav_links = self._extract_nav_links(soup, url, base_domain)
                if not nav_links:
                    continue

                page_text = self._extract_page_text_snippets(soup)

                # Call LLM
                suggestions = self._ask_llm_for_links(
                    llm_fn, url, nav_links, page_text, language_hint=language_hint,
                )
                if suggestions:
                    urls_to_explore.extend(suggestions)

            except PlaywrightTimeout:
                logger.debug("    LLM path: timeout loading %s", url)
            except Exception as exc:
                logger.debug("    LLM path: error loading %s: %s", url, exc)

        return None

    def _extract_nav_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
    ) -> list[dict]:
        """Extract a compact list of navigational links for the LLM."""
        links: list[dict] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            abs_url = urljoin(page_url, href)

            if self._get_domain(abs_url) != base_domain:
                continue
            if _SKIP_RE.search(abs_url):
                continue
            norm = self._normalize_url(abs_url)
            if norm in self.visited_urls or norm in seen:
                continue
            seen.add(norm)

            text = a.get_text(strip=True)
            if not text or len(text) > 100:
                continue

            context = self._get_link_context(a, max_chars=150)
            is_pdf = self._is_pdf_url(abs_url)

            links.append({
                "url": abs_url,
                "text": text,
                "context": context if context != text.lower() else "",
                "is_pdf": is_pdf,
            })

        # Cap at 40 links to keep tokens low
        return links[:40]

    @staticmethod
    def _extract_page_text_snippets(soup: BeautifulSoup, max_len: int = 500) -> str:
        """Extract key text snippets from the page (headings + paragraphs)."""
        parts: list[str] = []
        for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            txt = tag.get_text(strip=True)
            if txt and len(txt) > 3:
                parts.append(txt)
        combined = " | ".join(parts)
        return combined[:max_len]

    def _ask_llm_for_links(
        self,
        llm_fn,
        page_url: str,
        nav_links: list[dict],
        page_text: str,
        language_hint: str = "en",
    ) -> list[str]:
        """Ask LLM which links most likely lead to a wine list.  Returns URLs."""
        # Build compact prompt
        links_compact = json.dumps(
            [{"url": l["url"], "text": l["text"],
              "context": l["context"], "is_pdf": l["is_pdf"]}
             for l in nav_links],
        )

        language_note = ""
        if language_hint == "fr":
            language_note = " The restaurant is in France; prefer links in French (e.g. Carte des vins, Vins) when present."
        elif language_hint == "es":
            language_note = " The restaurant is in Spain or Mexico; prefer links in Spanish (e.g. Carta de vinos, Vinos) when present."

        prompt = f"""Analyze this restaurant website page to find their wine list.
The site may be in English, French, or Spanish. Look for wine-list links in any of these languages.

Page URL: {page_url}
Page text snippets: {page_text}

Links on this page:
{links_compact}

Which links are most likely to lead to the restaurant's wine list?
Consider:
- Direct PDF links with wine/beverage in the name
- Links with text like "Wine List", "Carte des vins", "Carta de vinos", "Beverage Program", "Carte des boissons", "Carta de bebidas"
- Links where surrounding context mentions wine (e.g. "wine list is available here", "carte des vins disponible", "carta de vinos disponible")
- Navigation items like "About", "Menus", "À propos", "Menús", "Nuestra carta" that commonly contain wine sections
- Informational pages like "FAQ" that sometimes have wine list links or policies
{language_note}

Return JSON only:
{{"links": ["url1", "url2"], "reasoning": "brief explanation"}}

Rules:
- Return 1-3 most promising URLs, ranked by likelihood
- If no link is promising at all, return {{"links": [], "reasoning": "no wine list path found"}}
- Prefer specific wine/beverage links over generic menu links
- PDF links with wine-related names are the best candidates"""

        try:
            response = llm_fn(
                model=f"{self.settings.llm_provider}/{self.settings.llm_model}",
                messages=[
                    {"role": "system", "content": (
                        "You are an expert at navigating restaurant websites to find "
                        "wine lists. Respond with valid JSON only, no markdown."
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
                api_key=self.settings.llm_api_key or None,
            )

            # Track tokens
            if hasattr(response, "usage") and response.usage:
                total = getattr(response.usage, "total_tokens", 0)
                self.tokens_used += total
                logger.debug("    LLM used %d tokens (total: %d)", total, self.tokens_used)

            content = response.choices[0].message.content.strip()

            # Strip markdown fences if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(
                    l for l in lines if not l.startswith("```")
                )

            result = json.loads(content)
            urls = result.get("links", [])
            reasoning = result.get("reasoning", "")

            if urls:
                logger.info("    LLM suggests: %s (%s)", urls, reasoning)
            else:
                logger.info("    LLM found no promising links: %s", reasoning)

            return urls

        except json.JSONDecodeError as exc:
            logger.debug("    LLM JSON parse error: %s", exc)
            return []
        except Exception as exc:
            logger.debug("    LLM call error: %s", exc)
            return []

    # ==================================================================
    # Shared helpers
    # ==================================================================

    def _verify_url(self, url: str) -> bool:
        """Quick check that a URL is reachable."""
        try:
            resp = self.page.goto(
                url,
                timeout=self.settings.browser_timeout,
                wait_until="domcontentloaded",
            )
            return bool(resp and resp.ok)
        except Exception:
            return False

    @staticmethod
    def _normalize_url(url: str) -> str:
        parsed = urlparse(url)
        out = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if out.endswith("/") and len(parsed.path) > 1:
            out = out[:-1]
        return out

    @staticmethod
    def _get_domain(url: str) -> str:
        return urlparse(url).netloc.lower()

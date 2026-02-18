"""Unit tests for RestaurantWineListFinder scoring and URL helpers.

These tests exercise the pure-logic methods that don't need a browser.
"""
import pytest
from unittest.mock import MagicMock

from winerank.crawler.restaurant_finder import (
    RestaurantWineListFinder,
    _SKIP_RE,
    _WINE_PLATFORM_RE,
)


@pytest.fixture
def finder():
    """Create a finder with a mock Playwright Page (no real browser)."""
    mock_page = MagicMock()
    return RestaurantWineListFinder(mock_page)


# ------------------------------------------------------------------
# _normalize_url
# ------------------------------------------------------------------

class TestNormalizeUrl:

    def test_strips_trailing_slash(self):
        assert (RestaurantWineListFinder._normalize_url("https://example.com/path/")
                == "https://example.com/path")

    def test_keeps_root_slash(self):
        assert (RestaurantWineListFinder._normalize_url("https://example.com/")
                == "https://example.com/")

    def test_drops_query_and_fragment(self):
        result = RestaurantWineListFinder._normalize_url(
            "https://example.com/page?q=1#section"
        )
        assert result == "https://example.com/page"


# ------------------------------------------------------------------
# _get_domain
# ------------------------------------------------------------------

class TestGetDomain:

    def test_basic(self):
        assert RestaurantWineListFinder._get_domain("https://www.example.com/path") == "www.example.com"

    def test_lowercase(self):
        assert RestaurantWineListFinder._get_domain("https://WWW.EXAMPLE.COM/") == "www.example.com"


# ------------------------------------------------------------------
# _is_pdf_url
# ------------------------------------------------------------------

class TestIsPdfUrl:

    def test_regular_pdf(self):
        assert RestaurantWineListFinder._is_pdf_url("https://site.com/wine-list.pdf")

    def test_url_encoded_pdf(self):
        assert RestaurantWineListFinder._is_pdf_url("https://site.com/wine-list.pdf%20")

    def test_html_not_pdf(self):
        assert not RestaurantWineListFinder._is_pdf_url("https://site.com/page.html")

    def test_no_extension(self):
        assert not RestaurantWineListFinder._is_pdf_url("https://site.com/page")


# ------------------------------------------------------------------
# _is_wine_platform_url
# ------------------------------------------------------------------

class TestIsWinePlatformUrl:

    def test_binwise_hub(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "https://hub.binwise.com/list/abc"
        )

    def test_bw_winelist_s3(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "http://bw-winelist-website-prod.s3-website-us-west-2.amazonaws.com/xxx"
        )

    def test_starwinelist(self):
        assert RestaurantWineListFinder._is_wine_platform_url(
            "https://www.starwinelist.com/download/abc"
        )

    def test_regular_url(self):
        assert not RestaurantWineListFinder._is_wine_platform_url(
            "https://www.example.com/wine"
        )


# ------------------------------------------------------------------
# _SKIP_RE – URLs that should be skipped
# ------------------------------------------------------------------

class TestSkipRegex:

    @pytest.mark.parametrize("url", [
        "https://instagram.com/restaurant",
        "https://facebook.com/restaurant",
        "https://www.opentable.com/reservation",
        "mailto:info@restaurant.com",
        "tel:+15551234567",
        "javascript:void(0)",
        "https://restaurant.com/careers",
        "https://restaurant.com/privacy",
        "https://restaurant.com/reservations",
        "https://restaurant.com/gift-cards",
        "https://restaurant.com/private-dining",
    ])
    def test_skips_irrelevant_urls(self, url):
        assert _SKIP_RE.search(url), f"Expected SKIP_RE to match: {url}"

    @pytest.mark.parametrize("url", [
        "https://restaurant.com/wine",
        "https://restaurant.com/menus",
        "https://restaurant.com/beverage-program",
        "https://restaurant.com/about",
    ])
    def test_allows_relevant_urls(self, url):
        assert not _SKIP_RE.search(url), f"Expected SKIP_RE to NOT match: {url}"


# ------------------------------------------------------------------
# _score_link
# ------------------------------------------------------------------

class TestScoreLink:

    def test_exact_wine_keyword_high_score(self, finder):
        score = finder._score_link("wine list", "/wine-list", "")
        assert score > 100

    def test_menu_keyword_lower_than_wine(self, finder):
        wine_score = finder._score_link("wine", "/wine", "")
        menu_score = finder._score_link("menus", "/menus", "")
        assert wine_score > menu_score

    def test_context_boosts_score(self, finder):
        base = finder._score_link("click here", "/link", "")
        boosted = finder._score_link("click here", "/link", "view our wine list here")
        assert boosted > base

    def test_faq_scores_at_menu_tier(self, finder):
        faq_score = finder._score_link("faq", "/faq", "")
        wine_score = finder._score_link("wine", "/wine", "")
        assert faq_score > 0, "FAQ should score > 0"
        assert wine_score > faq_score, "Wine should score higher than FAQ"

    def test_chefs_counter_scores(self, finder):
        score = finder._score_link("chef's counter", "/chefs-counter", "")
        assert score > 0, "Chef's Counter should score > 0"

    def test_tasting_menu_scores(self, finder):
        score = finder._score_link("tasting menu", "/tasting-menu", "")
        assert score > 0, "Tasting Menu should score > 0"

    def test_about_scores_low(self, finder):
        about_score = finder._score_link("about", "/about", "")
        assert about_score > 0, "About should score > 0"

    def test_no_match_returns_zero(self, finder):
        score = finder._score_link("reservations now", "/reserve", "")
        assert score == 0

    def test_href_slug_match(self, finder):
        score = finder._score_link("selections", "/wine-selections", "")
        assert score > 0

    def test_beverage_program_scores(self, finder):
        score = finder._score_link("beverage program", "/beverage-program", "")
        assert score > 0


# ------------------------------------------------------------------
# _score_wine_keywords_only (stricter — external links)
# ------------------------------------------------------------------

class TestScoreWineKeywordsOnly:

    def test_wine_keyword_scores(self, finder):
        score = finder._score_wine_keywords_only("wine list", "/wine-list")
        assert score > 50

    def test_menu_keyword_does_not_score(self, finder):
        score = finder._score_wine_keywords_only("menus", "/menus")
        assert score == 0

    def test_beverage_keyword_scores(self, finder):
        score = finder._score_wine_keywords_only("beverage menu", "/beverage")
        assert score > 0


# ------------------------------------------------------------------
# _normalize_text (accent normalization)
# ------------------------------------------------------------------

class TestNormalizeText:

    def test_lowercase(self):
        assert RestaurantWineListFinder._normalize_text("Wine List") == "wine list"

    def test_strips_accents(self):
        assert RestaurantWineListFinder._normalize_text("café") == "cafe"
        assert RestaurantWineListFinder._normalize_text("dégustation") == "degustation"

    def test_empty(self):
        assert RestaurantWineListFinder._normalize_text("") == ""
        assert RestaurantWineListFinder._normalize_text("   ") == ""


# ------------------------------------------------------------------
# French (fr) keyword scoring – effective lists merged when language_hint is fr
# ------------------------------------------------------------------

class TestFrenchKeywordScoring:

    def test_french_wine_link_scores_when_effective_lists_include_fr(self, finder):
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_FR
        finder._effective_menu_keywords = finder.MENU_KEYWORDS + finder.MENU_KEYWORDS_FR
        finder._effective_informational_keywords = finder.INFORMATIONAL_KEYWORDS + finder.INFORMATIONAL_KEYWORDS_FR
        finder._effective_context_phrases = finder._CONTEXT_PHRASES + finder._CONTEXT_PHRASES_FR
        finder._effective_pdf_wine_terms = finder._PDF_WINE_TERMS + finder._PDF_WINE_TERMS_FR
        finder._build_norm_lists()

        score = finder._score_link("carte des vins", "/carte-des-vins", "")
        assert score > 50, "French 'carte des vins' link should score when FR keywords are active"

    def test_french_context_phrase_boosts_generic_link(self, finder):
        finder._effective_context_phrases = finder._CONTEXT_PHRASES + finder._CONTEXT_PHRASES_FR
        finder._build_norm_lists()
        # Generic link "ici" with French context mentioning wine list
        base = finder._score_link("ici", "/here", "")
        boosted = finder._score_link(
            "ici", "/here",
            "La carte des vins est disponible ici.",
        )
        assert boosted > base, "French context phrase should boost score for generic link"

    def test_french_wine_keywords_only_scores(self, finder):
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_FR
        finder._build_norm_lists()
        score = finder._score_wine_keywords_only("carte des vins", "/carte-des-vins")
        assert score > 0


# ------------------------------------------------------------------
# Spanish (es) keyword scoring
# ------------------------------------------------------------------

class TestSpanishKeywordScoring:

    def test_spanish_wine_link_scores_when_effective_lists_include_es(self, finder):
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_ES
        finder._effective_menu_keywords = finder.MENU_KEYWORDS + finder.MENU_KEYWORDS_ES
        finder._effective_informational_keywords = finder.INFORMATIONAL_KEYWORDS + finder.INFORMATIONAL_KEYWORDS_ES
        finder._effective_context_phrases = finder._CONTEXT_PHRASES + finder._CONTEXT_PHRASES_ES
        finder._effective_pdf_wine_terms = finder._PDF_WINE_TERMS + finder._PDF_WINE_TERMS_ES
        finder._build_norm_lists()

        score = finder._score_link("carta de vinos", "/carta-de-vinos", "")
        assert score > 50, "Spanish 'carta de vinos' link should score when ES keywords are active"

    def test_spanish_lista_vinos_scores(self, finder):
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_ES
        finder._build_norm_lists()
        score = finder._score_wine_keywords_only("lista de vinos", "/lista-de-vinos")
        assert score > 0


# ------------------------------------------------------------------
# _build_norm_lists – output correctness
# ------------------------------------------------------------------

class TestBuildNormLists:

    def test_norm_lists_populated_on_init(self, finder):
        """A freshly created finder must have _norm_wine_keywords ready."""
        assert len(finder._norm_wine_keywords) == len(finder.WINE_KEYWORDS)
        # All entries must be lowercase and accent-free
        assert all(kw == kw.lower() for kw in finder._norm_wine_keywords)

    def test_norm_lists_updated_after_build(self, finder):
        """After switching to FR, _norm_wine_keywords reflects the merged list."""
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_FR
        finder._build_norm_lists()
        assert len(finder._norm_wine_keywords) == len(finder.WINE_KEYWORDS) + len(finder.WINE_KEYWORDS_FR)
        # French keyword 'carte des vins' must appear in normalized form
        assert "carte des vins" in finder._norm_wine_keywords

    def test_accented_keywords_normalized_in_norm_lists(self, finder):
        """Accented FR/ES keywords are stored without accents in norm lists."""
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_FR
        finder._effective_menu_keywords = finder.MENU_KEYWORDS + finder.MENU_KEYWORDS_FR
        finder._build_norm_lists()
        # "dégustation" from MENU_KEYWORDS_FR must appear as "degustation"
        assert "degustation" in finder._norm_menu_keywords


# ------------------------------------------------------------------
# find_wine_list – effective-list setup via language_hint (no browser needed)
# ------------------------------------------------------------------

class TestFindWineListEffectiveLists:

    def test_fr_hint_merges_french_keywords(self):
        """find_wine_list(language_hint='fr') loads FR+EN keywords."""
        mock_page = MagicMock()
        # Make page.content() return empty HTML so _smart_search returns None quickly
        mock_page.content.return_value = "<html><body></body></html>"
        mock_page.goto.return_value = MagicMock(ok=True)
        finder = RestaurantWineListFinder(mock_page)
        finder.find_wine_list("https://example.com", language_hint="fr")
        assert "carte des vins" in finder._effective_wine_keywords
        assert "wine list" in finder._effective_wine_keywords  # English still present

    def test_es_hint_merges_spanish_keywords(self):
        """find_wine_list(language_hint='es') loads ES+EN keywords."""
        mock_page = MagicMock()
        mock_page.content.return_value = "<html><body></body></html>"
        mock_page.goto.return_value = MagicMock(ok=True)
        finder = RestaurantWineListFinder(mock_page)
        finder.find_wine_list("https://example.com", language_hint="es")
        assert "carta de vinos" in finder._effective_wine_keywords
        assert "wine list" in finder._effective_wine_keywords

    def test_no_hint_uses_english_only(self):
        """find_wine_list without language_hint uses only English keywords."""
        mock_page = MagicMock()
        mock_page.content.return_value = "<html><body></body></html>"
        mock_page.goto.return_value = MagicMock(ok=True)
        finder = RestaurantWineListFinder(mock_page)
        finder.find_wine_list("https://example.com")
        assert "carte des vins" not in finder._effective_wine_keywords
        assert "carta de vinos" not in finder._effective_wine_keywords


# ------------------------------------------------------------------
# _score_pdf with French / Spanish PDF wine terms
# ------------------------------------------------------------------

class TestScorePdfMultilingual:

    def _tag_with_text(self, text: str):
        """Return a minimal BeautifulSoup <a> tag with the given text."""
        from bs4 import BeautifulSoup
        html = f"<a href='/doc'>{text}</a>"
        return BeautifulSoup(html, "html.parser").find("a")

    def test_french_pdf_term_in_url_scores(self, finder):
        finder._effective_pdf_wine_terms = finder._PDF_WINE_TERMS + finder._PDF_WINE_TERMS_FR
        finder._build_norm_lists()
        tag = self._tag_with_text("Download")
        score = finder._score_pdf("https://restaurant.fr/carte-des-vins.pdf", tag)
        assert score > 0, "PDF URL containing 'carte' should score with FR terms active"

    def test_spanish_pdf_term_in_url_scores(self, finder):
        finder._effective_pdf_wine_terms = finder._PDF_WINE_TERMS + finder._PDF_WINE_TERMS_ES
        finder._build_norm_lists()
        tag = self._tag_with_text("Download")
        score = finder._score_pdf("https://restaurant.es/bodega-vinos.pdf", tag)
        assert score > 0, "PDF URL containing 'bodega' should score with ES terms active"


# ------------------------------------------------------------------
# Accent normalization in full scoring pipeline
# ------------------------------------------------------------------

class TestAccentNormalizationInScoring:

    def test_accented_link_text_matches_fr_keyword(self, finder):
        """Link text 'Dégustation' should match the French keyword 'degustation'."""
        finder._effective_menu_keywords = finder.MENU_KEYWORDS + finder.MENU_KEYWORDS_FR
        finder._build_norm_lists()
        score = finder._score_link("Dégustation", "/degustation", "")
        assert score > 0, "Accented link text should match normalized French keyword"

    def test_accented_href_matches_fr_keyword(self, finder):
        """Href slug 'carte-des-vins' derived from an accented keyword should match."""
        finder._effective_wine_keywords = finder.WINE_KEYWORDS + finder.WINE_KEYWORDS_FR
        finder._build_norm_lists()
        score = finder._score_link("Voir la carte", "/carte-des-vins", "")
        assert score > 0, "Href 'carte-des-vins' should match normalized French wine keyword"


# ------------------------------------------------------------------
# English-only behavior unchanged when language_hint is en / None
# ------------------------------------------------------------------

class TestEnglishOnlyUnchanged:

    def test_wine_list_still_scores_high_with_default_lists(self, finder):
        score = finder._score_link("wine list", "/wine-list", "")
        assert score > 100


# ------------------------------------------------------------------
# Metrics tracking
# ------------------------------------------------------------------

class TestMetrics:

    def test_initial_counters(self, finder):
        assert finder.pages_loaded == 0
        assert finder.tokens_used == 0
        assert len(finder.visited_urls) == 0

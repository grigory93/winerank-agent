"""Tests for site resolution and seed data."""
import pytest

from winerank.common.db import resolve_site_by_name
from winerank.common.models import SiteOfRecord
from winerank.cli import SITES_OF_RECORD


# ------------------------------------------------------------------
# SITES_OF_RECORD constant
# ------------------------------------------------------------------

def test_sites_of_record_has_six_entries():
    assert len(SITES_OF_RECORD) == 6


def test_sites_of_record_includes_usa_and_short_names():
    names = [n for n, _ in SITES_OF_RECORD]
    assert "Michelin Guide USA" in names
    assert "Michelin Guide France" in names
    assert "Michelin Guide Spain" in names


# ------------------------------------------------------------------
# resolve_site_by_name
# ------------------------------------------------------------------

class TestResolveSiteByName:

    def test_exact_match_case_insensitive(self, test_session):
        site = SiteOfRecord(
            site_name="Michelin Guide USA",
            site_url="https://guide.michelin.com/us/en/selection/united-states/restaurants",
        )
        test_session.add(site)
        test_session.commit()
        found = resolve_site_by_name(test_session, "Michelin Guide USA")
        assert found is not None
        assert found.site_name == "Michelin Guide USA"
        found2 = resolve_site_by_name(test_session, "michelin guide usa")
        assert found2 is not None
        assert found2.id == found.id

    def test_short_name_usa(self, test_session):
        site = SiteOfRecord(
            site_name="Michelin Guide USA",
            site_url="https://guide.michelin.com/us/en/selection/united-states/restaurants",
        )
        test_session.add(site)
        test_session.commit()
        found = resolve_site_by_name(test_session, "USA")
        assert found is not None
        assert found.site_name == "Michelin Guide USA"
        found2 = resolve_site_by_name(test_session, "usa")
        assert found2 is not None
        assert found2.id == found.id

    def test_short_name_canada(self, test_session):
        site = SiteOfRecord(
            site_name="Michelin Guide Canada",
            site_url="https://guide.michelin.com/us/en/selection/canada/restaurants",
        )
        test_session.add(site)
        test_session.commit()
        found = resolve_site_by_name(test_session, "Canada")
        assert found is not None
        assert found.site_name == "Michelin Guide Canada"

    def test_empty_or_whitespace_returns_none(self, test_session):
        site = SiteOfRecord(
            site_name="Michelin Guide USA",
            site_url="https://guide.michelin.com/us/en/selection/united-states/restaurants",
        )
        test_session.add(site)
        test_session.commit()
        assert resolve_site_by_name(test_session, "") is None
        assert resolve_site_by_name(test_session, "   ") is None

    def test_no_match_returns_none(self, test_session):
        assert resolve_site_by_name(test_session, "NoSuchSite") is None
        assert resolve_site_by_name(test_session, "garbage") is None

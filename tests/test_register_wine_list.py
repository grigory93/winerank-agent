"""Tests for register-wine-list CLI command."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from winerank.cli import app
from winerank.common.models import CrawlStatus, Restaurant, SiteOfRecord, WineList


runner = CliRunner()


@pytest.fixture
def seeded_session(test_session):
    """Create SiteOfRecord and Restaurant with PENDING status."""
    site = SiteOfRecord(
        site_name="Michelin Guide USA",
        site_url="https://guide.michelin.com/us/en/",
        navigational_notes="",
    )
    test_session.add(site)
    test_session.commit()

    rest = Restaurant(
        name="Test Restaurant",
        website_url="https://example.com",
        crawl_status=CrawlStatus.PENDING,
        country="USA",
        site_of_record_id=site.id,
    )
    test_session.add(rest)
    test_session.commit()
    return test_session


def test_register_wine_list_updates_restaurant_status(seeded_session, tmp_path):
    """register-wine-list sets restaurant crawl_status to WINE_LIST_FOUND."""
    # Minimal file so path.read_bytes() and is_file() succeed
    pdf_path = tmp_path / "wine_list.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 minimal\n%%EOF")

    @contextmanager
    def fake_get_session():
        yield seeded_session

    with (
        patch("winerank.common.db.get_session", side_effect=fake_get_session),
        patch(
            "winerank.crawler.text_extractor.WineListTextExtractor.extract_and_save",
            return_value=str(pdf_path.with_suffix(".txt")),
        ),
    ):
        result = runner.invoke(
            app,
            ["register-wine-list", "--restaurant", "Test Restaurant", "--file", str(pdf_path)],
        )

    assert result.exit_code == 0, result.output

    seeded_session.expire_all()  # refresh from DB
    rest = seeded_session.query(Restaurant).filter_by(name="Test Restaurant").first()
    assert rest is not None
    assert rest.crawl_status == CrawlStatus.WINE_LIST_FOUND
    assert seeded_session.query(WineList).filter_by(restaurant_id=rest.id).first() is not None

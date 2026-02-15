"""Test database models."""
import pytest
from datetime import datetime

from winerank.common.models import (
    SiteOfRecord,
    Restaurant,
    WineList,
    Wine,
    Job,
    CrawlStatus,
    JobStatus,
    MichelinDistinction,
)


def test_create_site_of_record(test_session):
    """Test creating a SiteOfRecord."""
    site = SiteOfRecord(
        site_name="Test Site",
        site_url="https://example.com",
        navigational_notes="Test notes",
    )
    test_session.add(site)
    test_session.commit()
    
    assert site.id is not None
    assert site.site_name == "Test Site"
    assert site.created_at is not None


def test_create_restaurant(test_session):
    """Test creating a Restaurant."""
    # Create site of record first
    site = SiteOfRecord(
        site_name="Test Site",
        site_url="https://example.com",
    )
    test_session.add(site)
    test_session.flush()
    
    restaurant = Restaurant(
        name="Test Restaurant",
        michelin_url="https://guide.michelin.com/test",
        website_url="https://restaurant.com",
        michelin_distinction=MichelinDistinction.THREE_STARS,
        city="New York",
        state="NY",
        country="USA",
        cuisine="French",
        price_range="$$$$",
        crawl_status=CrawlStatus.PENDING,
        site_of_record_id=site.id,
    )
    test_session.add(restaurant)
    test_session.commit()
    
    assert restaurant.id is not None
    assert restaurant.name == "Test Restaurant"
    assert restaurant.michelin_distinction == MichelinDistinction.THREE_STARS
    assert restaurant.crawl_status == CrawlStatus.PENDING


def test_restaurant_wine_list_relationship(test_session):
    """Test Restaurant -> WineList relationship."""
    # Create site and restaurant
    site = SiteOfRecord(site_name="Test", site_url="https://example.com")
    test_session.add(site)
    test_session.flush()
    
    restaurant = Restaurant(
        name="Test Restaurant",
        site_of_record_id=site.id,
    )
    test_session.add(restaurant)
    test_session.flush()
    
    # Create wine list
    wine_list = WineList(
        restaurant_id=restaurant.id,
        source_url="https://restaurant.com/wines.pdf",
        local_file_path="/tmp/wines.pdf",
        file_hash="abc123",
    )
    test_session.add(wine_list)
    test_session.commit()
    
    # Test relationship
    assert len(restaurant.wine_lists) == 1
    assert restaurant.wine_lists[0].id == wine_list.id


def test_wine_list_wines_relationship(test_session):
    """Test WineList -> Wine relationship."""
    # Create necessary parent records
    site = SiteOfRecord(site_name="Test", site_url="https://example.com")
    test_session.add(site)
    test_session.flush()
    
    restaurant = Restaurant(name="Test", site_of_record_id=site.id)
    test_session.add(restaurant)
    test_session.flush()
    
    wine_list = WineList(
        restaurant_id=restaurant.id,
        source_url="https://test.com/wines.pdf",
        local_file_path="/tmp/wines.pdf",
        file_hash="abc123",
    )
    test_session.add(wine_list)
    test_session.flush()
    
    # Create wines
    wine1 = Wine(
        wine_list_id=wine_list.id,
        name="Château Margaux",
        winery="Château Margaux",
        varietal="Bordeaux Blend",
        wine_type="Red",
        country="France",
        region="Bordeaux",
        vintage="2015",
        price=500.00,
    )
    wine2 = Wine(
        wine_list_id=wine_list.id,
        name="Dom Pérignon",
        winery="Moët & Chandon",
        varietal="Champagne",
        wine_type="Sparkling",
        country="France",
        vintage="2010",
        price=300.00,
    )
    test_session.add_all([wine1, wine2])
    test_session.commit()
    
    # Test relationship
    assert len(wine_list.wines) == 2
    assert wine_list.wine_count == 0  # Not auto-updated
    
    # Update wine count
    wine_list.wine_count = len(wine_list.wines)
    test_session.commit()
    assert wine_list.wine_count == 2


def test_job_creation(test_session):
    """Test Job creation."""
    site = SiteOfRecord(site_name="Test", site_url="https://example.com")
    test_session.add(site)
    test_session.flush()
    
    job = Job(
        job_type="crawler",
        michelin_level="3",
        status=JobStatus.RUNNING,
        site_of_record_id=site.id,
    )
    test_session.add(job)
    test_session.commit()
    
    assert job.id is not None
    assert job.status == JobStatus.RUNNING
    assert job.started_at is not None


def test_cascade_delete(test_session):
    """Test cascade delete behavior."""
    # Create full hierarchy
    site = SiteOfRecord(site_name="Test", site_url="https://example.com")
    test_session.add(site)
    test_session.flush()
    
    restaurant = Restaurant(name="Test", site_of_record_id=site.id)
    test_session.add(restaurant)
    test_session.flush()
    
    wine_list = WineList(
        restaurant_id=restaurant.id,
        source_url="https://test.com/wines.pdf",
        local_file_path="/tmp/wines.pdf",
        file_hash="abc123",
    )
    test_session.add(wine_list)
    test_session.flush()
    
    wine = Wine(wine_list_id=wine_list.id, name="Test Wine")
    test_session.add(wine)
    test_session.commit()
    
    # Delete restaurant should cascade to wine_list and wine
    test_session.delete(restaurant)
    test_session.commit()
    
    # Verify cascade
    assert test_session.query(WineList).filter_by(id=wine_list.id).first() is None
    assert test_session.query(Wine).filter_by(id=wine.id).first() is None

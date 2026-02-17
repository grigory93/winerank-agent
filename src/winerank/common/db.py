"""Database session management and utilities."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from winerank.config import get_settings


# Create engine lazily
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    """Get or create the SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=False,  # Set to True for SQL logging during development
            pool_pre_ping=True,  # Verify connections before using them
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions.
    
    Usage:
        with get_session() as session:
            restaurant = session.query(Restaurant).first()
            session.commit()
    """
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_restaurant_by_id_or_name(identifier: str) -> Optional["Restaurant"]:
    """Look up a restaurant by ID (if numeric) or name (case-insensitive).

    Strips whitespace from identifier. Tries exact name match first, then partial.
    Returns the Restaurant ORM object or None if not found.
    """
    from winerank.common.models import Restaurant

    value = identifier.strip()
    if not value:
        return None
    with get_session() as session:
        if value.isdigit():
            return session.query(Restaurant).filter_by(id=int(value)).first()
        rec = session.query(Restaurant).filter(Restaurant.name.ilike(value)).first()
        if rec:
            return rec
        return (
            session.query(Restaurant).filter(Restaurant.name.ilike(f"%{value}%")).first()
        )


def init_db() -> None:
    """Initialize database by creating all tables."""
    from winerank.common.models import Base
    
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def drop_all_tables() -> None:
    """Drop all tables (use with caution!)."""
    from winerank.common.models import Base
    
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)


def reset_db() -> None:
    """Reset database by dropping and recreating all tables."""
    drop_all_tables()
    init_db()

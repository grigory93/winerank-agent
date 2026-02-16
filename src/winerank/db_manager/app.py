"""Streamlit database manager application."""
import streamlit as st

from winerank.common.db import get_engine, get_session_factory

# Page configuration - must be the first Streamlit command
st.set_page_config(
    page_title="Winerank DB Manager",
    page_icon="\U0001f377",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Cache the database engine
@st.cache_resource
def get_cached_engine():
    """Get cached SQLAlchemy engine."""
    return get_engine()


@st.cache_resource
def get_cached_session_factory():
    """Get cached session factory."""
    return get_session_factory()


# Initialize engine
engine = get_cached_engine()
SessionLocal = get_cached_session_factory()

# Import page modules
from winerank.db_manager.pages import (  # noqa: E402
    jobs,
    reports,
    restaurants,
    sites_of_record,
    wine_lists,
    wines,
)

# Define navigation using st.navigation (replaces auto-detected pages/ sidebar)
pg = st.navigation(
    [
        st.Page(reports.render, title="Reports", icon="\U0001f4ca", url_path="reports", default=True),
        st.Page(restaurants.render, title="Restaurants", icon="\U0001f3ea", url_path="restaurants"),
        st.Page(wine_lists.render, title="Wine Lists", icon="\U0001f4c4", url_path="wine-lists"),
        st.Page(wines.render, title="Wines", icon="\U0001f377", url_path="wines"),
        st.Page(jobs.render, title="Jobs", icon="\u2699\ufe0f", url_path="jobs"),
        st.Page(
            sites_of_record.render,
            title="Sites of Record",
            icon="\U0001f310",
            url_path="sites",
        ),
    ]
)

# Sidebar extras below the navigation links
st.sidebar.markdown("---")
st.sidebar.markdown("### Database")
try:
    with engine.connect() as conn:
        st.sidebar.success("\u2713 Connected")
except Exception as e:
    st.sidebar.error(f"\u2717 Connection failed: {e}")

# Run the selected page
pg.run()

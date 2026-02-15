"""Streamlit database manager application."""
import streamlit as st
from sqlalchemy.orm import Session

from winerank.common.db import get_engine, get_session_factory

# Page configuration
st.set_page_config(
    page_title="Winerank DB Manager",
    page_icon="🍷",
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

# Sidebar navigation
st.sidebar.title("🍷 Winerank DB Manager")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigation",
    [
        "📊 Reports",
        "🏪 Restaurants",
        "📄 Wine Lists",
        "🍷 Wines",
        "⚙️ Jobs",
        "🌐 Sites of Record",
    ],
)

st.sidebar.markdown("---")
st.sidebar.markdown("### Database Status")

# Check database connection
try:
    with engine.connect() as conn:
        st.sidebar.success("✓ Connected")
except Exception as e:
    st.sidebar.error(f"✗ Connection failed: {e}")

# Import and run the appropriate page
if page == "📊 Reports":
    from winerank.db_manager.pages import reports
    reports.render()
elif page == "🏪 Restaurants":
    from winerank.db_manager.pages import restaurants
    restaurants.render()
elif page == "📄 Wine Lists":
    from winerank.db_manager.pages import wine_lists
    wine_lists.render()
elif page == "🍷 Wines":
    from winerank.db_manager.pages import wines
    wines.render()
elif page == "⚙️ Jobs":
    from winerank.db_manager.pages import jobs
    jobs.render()
elif page == "🌐 Sites of Record":
    from winerank.db_manager.pages import sites_of_record
    sites_of_record.render()

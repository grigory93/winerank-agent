"""Reports page - summary metrics and dashboards."""
import streamlit as st
from sqlalchemy import func, select

from winerank.common.db import get_session
from winerank.common.models import Restaurant, WineList, Wine, Job, CrawlStatus, JobStatus


def render():
    """Render the Reports page."""
    st.title("📊 Reports Dashboard")
    
    with get_session() as session:
        # Top metrics row
        col1, col2, col3, col4 = st.columns(4)
        
        # Total restaurants
        total_restaurants = session.query(func.count(Restaurant.id)).scalar()
        col1.metric("Total Restaurants", total_restaurants)
        
        # Restaurants with wine lists
        restaurants_with_lists = session.query(func.count(Restaurant.id)).filter(
            Restaurant.crawl_status == CrawlStatus.WINE_LIST_FOUND
        ).scalar()
        col2.metric("Restaurants w/ Wine Lists", restaurants_with_lists)
        
        # Total wine lists
        total_wine_lists = session.query(func.count(WineList.id)).scalar()
        col3.metric("Total Wine Lists", total_wine_lists)
        
        # Total wines
        total_wines = session.query(func.count(Wine.id)).scalar()
        col4.metric("Total Wines", total_wines)
        
        st.markdown("---")
        
        # Crawl coverage
        st.subheader("Crawl Coverage")
        if total_restaurants > 0:
            coverage_pct = (restaurants_with_lists / total_restaurants) * 100
            st.progress(restaurants_with_lists / total_restaurants)
            st.write(f"**{coverage_pct:.1f}%** of restaurants have wine lists downloaded")
        else:
            st.info("No restaurants in database yet")
        
        st.markdown("---")
        
        # Restaurant breakdown by distinction
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Restaurants by Distinction")
            distinction_counts = session.query(
                Restaurant.michelin_distinction,
                func.count(Restaurant.id).label("count")
            ).group_by(Restaurant.michelin_distinction).all()
            
            if distinction_counts:
                for distinction, count in distinction_counts:
                    st.write(f"**{distinction or 'Unknown'}**: {count}")
            else:
                st.info("No restaurants categorized yet")
        
        with col2:
            st.subheader("Restaurants by Crawl Status")
            status_counts = session.query(
                Restaurant.crawl_status,
                func.count(Restaurant.id).label("count")
            ).group_by(Restaurant.crawl_status).all()
            
            if status_counts:
                for status, count in status_counts:
                    st.write(f"**{status.value}**: {count}")
            else:
                st.info("No status data yet")
        
        st.markdown("---")
        
        # Recent jobs
        st.subheader("Recent Jobs")
        recent_jobs = session.query(Job).order_by(Job.started_at.desc()).limit(10).all()
        
        if recent_jobs:
            job_data = []
            for job in recent_jobs:
                job_data.append({
                    "ID": job.id,
                    "Type": job.job_type,
                    "Level": job.michelin_level or "N/A",
                    "Status": job.status.value,
                    "Progress": f"{job.restaurants_processed}/{job.restaurants_found}",
                    "Wine Lists": job.wine_lists_downloaded,
                    "Started": job.started_at.strftime("%Y-%m-%d %H:%M"),
                })
            st.dataframe(job_data, use_container_width=True)
        else:
            st.info("No jobs run yet")

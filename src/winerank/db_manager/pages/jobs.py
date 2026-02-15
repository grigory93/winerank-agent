"""Jobs page - view crawler job status and history."""
import streamlit as st
import pandas as pd

from winerank.common.db import get_session
from winerank.common.models import Job, JobStatus


def render():
    """Render the Jobs page."""
    st.title("⚙️ Crawler Jobs")
    
    # Filter by status
    filter_status = st.multiselect(
        "Filter by Status",
        options=[s.value for s in JobStatus],
        default=[],
    )
    
    st.markdown("---")
    
    with get_session() as session:
        # Query jobs
        query = session.query(Job).order_by(Job.started_at.desc())
        
        if filter_status:
            query = query.filter(Job.status.in_(filter_status))
        
        jobs = query.all()
        
        st.write(f"**Total: {len(jobs)} jobs**")
        
        if jobs:
            # Summary statistics
            col1, col2, col3, col4 = st.columns(4)
            
            completed_jobs = [j for j in jobs if j.status == JobStatus.COMPLETED]
            running_jobs = [j for j in jobs if j.status == JobStatus.RUNNING]
            failed_jobs = [j for j in jobs if j.status == JobStatus.FAILED]
            
            col1.metric("Total Jobs", len(jobs))
            col2.metric("Completed", len(completed_jobs))
            col3.metric("Running", len(running_jobs))
            col4.metric("Failed", len(failed_jobs))
            
            st.markdown("---")
            
            # Jobs list
            for job in jobs:
                # Determine status color
                status_colors = {
                    JobStatus.COMPLETED: "🟢",
                    JobStatus.RUNNING: "🔵",
                    JobStatus.FAILED: "🔴",
                    JobStatus.PENDING: "⚪",
                    JobStatus.CANCELLED: "⚫",
                }
                status_icon = status_colors.get(job.status, "⚪")
                
                with st.expander(
                    f"{status_icon} Job #{job.id} - {job.job_type} ({job.status.value}) - {job.started_at.strftime('%Y-%m-%d %H:%M')}",
                    expanded=(job.status == JobStatus.RUNNING)
                ):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.write(f"**Type:** {job.job_type}")
                        st.write(f"**Michelin Level:** {job.michelin_level or 'N/A'}")
                        st.write(f"**Status:** {job.status.value}")
                        st.write(f"**Started:** {job.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
                        if job.completed_at:
                            st.write(f"**Completed:** {job.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
                        if job.duration_seconds:
                            mins = int(job.duration_seconds // 60)
                            secs = int(job.duration_seconds % 60)
                            st.write(f"**Duration:** {mins}m {secs}s")
                    
                    with col2:
                        st.write(f"**Total Pages:** {job.total_pages}")
                        st.write(f"**Current Page:** {job.current_page}")
                        st.write(f"**Restaurants Found:** {job.restaurants_found}")
                        st.write(f"**Restaurants Processed:** {job.restaurants_processed}")
                        
                        # Progress bar
                        if job.restaurants_found > 0:
                            progress = job.restaurants_processed / job.restaurants_found
                            st.progress(progress)
                            st.write(f"{progress*100:.1f}% complete")
                    
                    with col3:
                        st.write(f"**Wine Lists Downloaded:** {job.wine_lists_downloaded}")
                        
                        if job.site_of_record:
                            st.write(f"**Site of Record:** {job.site_of_record.site_name}")
                        
                        if job.error_message:
                            st.error(f"**Error:** {job.error_message}")
        else:
            st.info("No jobs found. Run the crawler to create jobs.")

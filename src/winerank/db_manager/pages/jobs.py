"""Jobs page - view crawler job status and history."""
import streamlit as st

from winerank.common.db import get_session
from winerank.common.models import Job, JobStatus

_STATUS_ICONS = {
    JobStatus.COMPLETED: "\U0001f7e2",
    JobStatus.RUNNING: "\U0001f535",
    JobStatus.FAILED: "\U0001f534",
    JobStatus.PENDING: "\u26aa",
    JobStatus.CANCELLED: "\u26ab",
}


def _fmt_duration(seconds) -> str:
    """Format duration in seconds to a human-readable string."""
    if seconds is None:
        return ""
    total = int(seconds)
    mins, secs = divmod(total, 60)
    return f"{mins}m {secs}s" if mins else f"{secs}s"


def render():
    """Render the Jobs page."""
    st.title("Crawler Jobs")

    filter_status = st.multiselect(
        "Filter by Status",
        options=[s.value for s in JobStatus],
        default=[],
    )

    st.markdown("---")

    with get_session() as session:
        query = session.query(Job).order_by(Job.started_at.desc())
        if filter_status:
            query = query.filter(Job.status.in_(filter_status))

        jobs = query.all()

        if not jobs:
            st.info("No jobs found. Run the crawler to create jobs.")
            return

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Jobs", len(jobs))
        col2.metric("Completed", sum(1 for j in jobs if j.status == JobStatus.COMPLETED))
        col3.metric("Running", sum(1 for j in jobs if j.status == JobStatus.RUNNING))
        col4.metric("Failed", sum(1 for j in jobs if j.status == JobStatus.FAILED))

        st.markdown("---")

        for job in jobs:
            icon = _STATUS_ICONS.get(job.status, "\u26aa")
            label = (
                f"{icon} Job #{job.id} \u2014 {job.job_type} ({job.status.value}) "
                f"\u2014 {job.started_at.strftime('%Y-%m-%d %H:%M')}"
            )

            with st.expander(label, expanded=(job.status == JobStatus.RUNNING)):
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.write(f"**Type:** {job.job_type}")
                    st.write(f"**Michelin Level:** {job.michelin_level or 'N/A'}")
                    st.write(f"**Status:** {job.status.value}")
                    st.write(f"**Started:** {job.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    if job.completed_at:
                        st.write(f"**Completed:** {job.completed_at.strftime('%Y-%m-%d %H:%M:%S')}")
                    duration = _fmt_duration(job.duration_seconds)
                    if duration:
                        st.write(f"**Duration:** {duration}")

                with col2:
                    st.write(f"**Total Pages:** {job.total_pages}")
                    st.write(f"**Current Page:** {job.current_page}")
                    st.write(f"**Restaurants Found:** {job.restaurants_found}")
                    st.write(f"**Restaurants Processed:** {job.restaurants_processed}")

                    if job.restaurants_found > 0:
                        progress = job.restaurants_processed / job.restaurants_found
                        st.progress(progress)
                        st.write(f"{progress * 100:.1f}% complete")

                with col3:
                    st.write(f"**Wine Lists Downloaded:** {job.wine_lists_downloaded}")

                    if job.site_of_record:
                        st.write(f"**Site of Record:** {job.site_of_record.site_name}")

                    if job.error_message:
                        st.error(f"**Error:** {job.error_message}")

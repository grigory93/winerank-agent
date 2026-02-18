"""Reports page - summary metrics and dashboards."""
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from winerank.common.db import get_session
from winerank.common.models import Restaurant, SiteOfRecord, WineList, Wine, Job, CrawlStatus, JobStatus


def render():
    """Render the Reports page."""
    st.title("Reports Dashboard")

    with get_session() as session:
        # ── Top-level metrics ──────────────────────────────────────
        col1, col2, col3, col4, col5 = st.columns(5)

        total_restaurants = session.query(func.count(Restaurant.id)).scalar()
        col1.metric("Restaurants", total_restaurants)

        wine_list_found = (
            session.query(func.count(Restaurant.id))
            .filter(Restaurant.crawl_status == CrawlStatus.WINE_LIST_FOUND)
            .scalar()
        )
        col2.metric("Wine Lists Found", wine_list_found)

        download_failed = (
            session.query(func.count(Restaurant.id))
            .filter(Restaurant.crawl_status == CrawlStatus.DOWNLOAD_LIST_FAILED)
            .scalar()
        )
        col3.metric("Download Failed", download_failed)

        total_wine_lists = session.query(func.count(WineList.id)).scalar()
        col4.metric("Downloaded Lists", total_wine_lists)

        total_wines = session.query(func.count(Wine.id)).scalar()
        col5.metric("Total Wines", total_wines)

        # ── Crawl coverage ─────────────────────────────────────────
        st.markdown("---")
        st.subheader("Crawl Coverage")
        if total_restaurants > 0:
            coverage_pct = (wine_list_found / total_restaurants) * 100
            st.progress(wine_list_found / total_restaurants)
            st.write(
                f"**{coverage_pct:.1f}%** of restaurants have wine lists found "
                f"({wine_list_found}/{total_restaurants})"
            )
        else:
            st.info("No restaurants in database yet")

        # ── Breakdowns by site, distinction and crawl status ──────
        st.markdown("---")
        st.subheader("By Site of Record")
        site_counts = (
            session.query(
                SiteOfRecord.site_name,
                func.count(Restaurant.id).label("count"),
            )
            .outerjoin(Restaurant, Restaurant.site_of_record_id == SiteOfRecord.id)
            .group_by(SiteOfRecord.id, SiteOfRecord.site_name)
            .order_by(SiteOfRecord.site_name)
            .all()
        )
        if site_counts:
            for site_name, count in site_counts:
                st.write(f"**{site_name}:** {count}")
        else:
            st.info("No sites of record yet (run `winerank db init`)")

        st.markdown("---")
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("By Distinction")
            distinction_counts = (
                session.query(
                    Restaurant.michelin_distinction,
                    func.count(Restaurant.id).label("count"),
                )
                .group_by(Restaurant.michelin_distinction)
                .all()
            )
            if distinction_counts:
                for distinction, count in distinction_counts:
                    label = distinction.value if distinction else "Unknown"
                    st.write(f"**{label}:** {count}")
            else:
                st.info("No data yet")

        with col2:
            st.subheader("By Crawl Status")
            status_counts = (
                session.query(
                    Restaurant.crawl_status,
                    func.count(Restaurant.id).label("count"),
                )
                .group_by(Restaurant.crawl_status)
                .all()
            )
            if status_counts:
                for status, count in status_counts:
                    st.write(f"**{status.value}:** {count}")
            else:
                st.info("No data yet")

        # ── Crawl statistics ───────────────────────────────────────
        st.markdown("---")
        st.subheader("Crawl Statistics")

        stats = (
            session.query(
                func.sum(Restaurant.llm_tokens_used).label("total_tokens"),
                func.sum(Restaurant.crawl_duration_seconds).label("total_time"),
                func.sum(Restaurant.pages_visited).label("total_pages"),
                func.avg(Restaurant.crawl_duration_seconds).label("avg_time"),
            )
            .filter(Restaurant.crawl_duration_seconds.isnot(None))
            .first()
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total LLM Tokens", f"{int(stats.total_tokens or 0):,}")

        total_time = float(stats.total_time or 0)
        mins = int(total_time // 60)
        secs = int(total_time % 60)
        col2.metric("Total Crawl Time", f"{mins}m {secs}s")

        col3.metric("Total Pages Visited", int(stats.total_pages or 0))

        avg_time = float(stats.avg_time or 0)
        col4.metric("Avg Crawl Time / Restaurant", f"{avg_time:.1f}s")

        # ── Recent jobs ────────────────────────────────────────────
        st.markdown("---")
        st.subheader("Recent Jobs")
        recent_jobs = (
            session.query(Job)
            .options(joinedload(Job.site_of_record))
            .order_by(Job.started_at.desc())
            .limit(10)
            .all()
        )

        if recent_jobs:
            job_data = []
            for job in recent_jobs:
                duration = ""
                if job.duration_seconds:
                    m = int(job.duration_seconds // 60)
                    s = int(job.duration_seconds % 60)
                    duration = f"{m}m {s}s"
                site_name = job.site_of_record.site_name if job.site_of_record else "N/A"
                job_data.append(
                    {
                        "ID": job.id,
                        "Site": site_name,
                        "Type": job.job_type,
                        "Level": job.michelin_level or "N/A",
                        "Status": job.status.value,
                        "Progress": f"{job.restaurants_processed}/{job.restaurants_found}",
                        "Wine Lists": job.wine_lists_downloaded,
                        "Duration": duration,
                        "Started": job.started_at.strftime("%Y-%m-%d %H:%M"),
                    }
                )
            st.dataframe(job_data, use_container_width=True)
        else:
            st.info("No jobs run yet")

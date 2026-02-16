"""Restaurants page - view and manage restaurants."""
import streamlit as st
import pandas as pd

from winerank.common.db import get_session
from winerank.common.models import Restaurant, MichelinDistinction, CrawlStatus


def render():
    """Render the Restaurants page."""
    st.title("Restaurants")

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        filter_distinction = st.multiselect(
            "Michelin Distinction",
            options=[d.value for d in MichelinDistinction],
            default=[],
        )

    with col2:
        filter_status = st.multiselect(
            "Crawl Status",
            options=[s.value for s in CrawlStatus],
            default=[],
        )

    with col3:
        filter_has_wine_list = st.selectbox(
            "Has Wine List",
            options=["All", "Yes", "No"],
            index=0,
        )

    st.markdown("---")

    with get_session() as session:
        query = session.query(Restaurant)

        if filter_distinction:
            query = query.filter(Restaurant.michelin_distinction.in_(filter_distinction))
        if filter_status:
            query = query.filter(Restaurant.crawl_status.in_(filter_status))
        if filter_has_wine_list == "Yes":
            query = query.filter(Restaurant.wine_list_url.isnot(None))
        elif filter_has_wine_list == "No":
            query = query.filter(Restaurant.wine_list_url.is_(None))

        restaurants = query.order_by(Restaurant.name).all()

        st.write(f"**Total: {len(restaurants)} restaurants**")

        if not restaurants:
            st.info("No restaurants match the selected filters")
            return

        # Build table data with new columns
        data = []
        for r in restaurants:
            duration = ""
            if r.crawl_duration_seconds:
                secs = float(r.crawl_duration_seconds)
                duration = f"{secs:.1f}s" if secs < 60 else f"{secs / 60:.1f}m"

            data.append(
                {
                    "ID": r.id,
                    "Name": r.name,
                    "Distinction": r.michelin_distinction.value if r.michelin_distinction else "",
                    "City": r.city or "",
                    "State": r.state or "",
                    "Status": r.crawl_status.value,
                    "Wine List": "\u2713" if r.wine_list_url else "\u2717",
                    "Crawl Time": duration,
                    "LLM Tokens": r.llm_tokens_used or 0,
                    "Pages": r.pages_visited or 0,
                    "Last Crawled": r.last_crawled_at.strftime("%Y-%m-%d") if r.last_crawled_at else "Never",
                }
            )

        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Detail view
        st.markdown("---")
        st.subheader("Restaurant Details")

        selected_id = st.number_input(
            "Select Restaurant ID to view details",
            min_value=1,
            max_value=max(r.id for r in restaurants),
            value=restaurants[0].id,
            step=1,
        )

        selected = session.query(Restaurant).filter_by(id=selected_id).first()

        if not selected:
            st.warning(f"Restaurant with ID {selected_id} not found")
            return

        col1, col2, col3 = st.columns(3)

        with col1:
            st.write(f"**Name:** {selected.name}")
            st.write(
                f"**Distinction:** {selected.michelin_distinction.value if selected.michelin_distinction else 'N/A'}"
            )
            st.write(f"**City:** {selected.city or 'N/A'}")
            st.write(f"**State:** {selected.state or 'N/A'}")
            st.write(f"**Country:** {selected.country}")
            st.write(f"**Cuisine:** {selected.cuisine or 'N/A'}")
            st.write(f"**Price Range:** {selected.price_range or 'N/A'}")

        with col2:
            st.write(f"**Status:** {selected.crawl_status.value}")
            if selected.website_url:
                st.write(f"**Website:** [{selected.website_url}]({selected.website_url})")
            else:
                st.write("**Website:** N/A")
            if selected.wine_list_url:
                st.write(f"**Wine List URL:** [{selected.wine_list_url}]({selected.wine_list_url})")
            else:
                st.write("**Wine List URL:** Not found")
            st.write(f"**Michelin URL:** {selected.michelin_url or 'N/A'}")
            st.write(f"**Last Crawled:** {selected.last_crawled_at or 'Never'}")

        with col3:
            st.write("**Crawl Statistics**")
            if selected.crawl_duration_seconds:
                secs = float(selected.crawl_duration_seconds)
                st.write(f"Duration: {secs:.1f}s")
            else:
                st.write("Duration: \u2014")
            st.write(f"LLM Tokens: {selected.llm_tokens_used or 0}")
            st.write(f"Pages Visited: {selected.pages_visited or 0}")

        if selected.comment:
            st.write(f"**Comment:** {selected.comment}")

        if selected.wine_lists:
            st.markdown("---")
            st.subheader("Wine Lists")
            for wl in selected.wine_lists:
                st.write(
                    f"- {wl.list_name or 'Unnamed'} ({wl.wine_count} wines) \u2014 "
                    f"Downloaded: {wl.downloaded_at.strftime('%Y-%m-%d')}"
                )

"""Wine Lists page - view downloaded wine lists."""
import streamlit as st
from pathlib import Path

from winerank.common.db import get_session
from winerank.common.models import WineList, Restaurant


def render():
    """Render the Wine Lists page."""
    st.title("Wine Lists")

    with get_session() as session:
        wine_lists = (
            session.query(WineList)
            .join(Restaurant)
            .order_by(Restaurant.name, WineList.downloaded_at.desc())
            .all()
        )

        if not wine_lists:
            st.info("No wine lists downloaded yet. Run the crawler to find and download wine lists.")
            return

        st.write(f"**Total: {len(wine_lists)} wine lists**")

        # Group by restaurant
        restaurants_dict: dict[str, list[WineList]] = {}
        for wl in wine_lists:
            rest_name = wl.restaurant.name
            restaurants_dict.setdefault(rest_name, []).append(wl)

        for rest_name, lists in restaurants_dict.items():
            suffix = "s" if len(lists) > 1 else ""
            with st.expander(f"{rest_name} ({len(lists)} list{suffix})", expanded=False):
                for wl in lists:
                    col1, col2 = st.columns([3, 1])

                    with col1:
                        st.write(f"**List:** {wl.list_name or 'Unnamed'}")
                        st.write(f"**Source:** {wl.source_url}")
                        st.write(f"**File:** `{wl.local_file_path}`")
                        if wl.text_file_path:
                            st.write(f"**Text:** `{wl.text_file_path}`")

                    with col2:
                        st.metric("Wines", wl.wine_count)
                        st.write(f"Downloaded: {wl.downloaded_at.strftime('%Y-%m-%d')}")
                        st.write(f"Hash: `{wl.file_hash[:8]}...`")

                    if wl.text_file_path and Path(wl.text_file_path).exists():
                        if st.button("View Text", key=f"view_text_{wl.id}"):
                            try:
                                text_content = Path(wl.text_file_path).read_text(encoding="utf-8")
                                st.text_area(
                                    "Extracted Text",
                                    text_content,
                                    height=400,
                                    key=f"text_area_{wl.id}",
                                )
                            except Exception as e:
                                st.error(f"Error reading text file: {e}")

                    if wl.comment:
                        st.info(f"Comment: {wl.comment}")

                    st.markdown("---")

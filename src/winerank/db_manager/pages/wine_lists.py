"""Wine Lists page - view downloaded wine lists."""
import streamlit as st
import pandas as pd
from pathlib import Path

from winerank.common.db import get_session
from winerank.common.models import WineList, Restaurant


def render():
    """Render the Wine Lists page."""
    st.title("📄 Wine Lists")
    
    with get_session() as session:
        # Get all wine lists with restaurant info
        wine_lists = session.query(WineList).join(Restaurant).order_by(
            Restaurant.name, WineList.downloaded_at.desc()
        ).all()
        
        if wine_lists:
            st.write(f"**Total: {len(wine_lists)} wine lists**")
            
            # Group by restaurant
            restaurants_dict = {}
            for wl in wine_lists:
                rest_name = wl.restaurant.name
                if rest_name not in restaurants_dict:
                    restaurants_dict[rest_name] = []
                restaurants_dict[rest_name].append(wl)
            
            # Display grouped by restaurant
            for rest_name, lists in restaurants_dict.items():
                with st.expander(f"{rest_name} ({len(lists)} list{'s' if len(lists) > 1 else ''})", expanded=False):
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
                        
                        # View text file button
                        if wl.text_file_path and Path(wl.text_file_path).exists():
                            if st.button(f"View Text", key=f"view_text_{wl.id}"):
                                try:
                                    with open(wl.text_file_path, 'r', encoding='utf-8') as f:
                                        text_content = f.read()
                                    st.text_area(
                                        "Extracted Text",
                                        text_content,
                                        height=400,
                                        key=f"text_area_{wl.id}"
                                    )
                                except Exception as e:
                                    st.error(f"Error reading text file: {e}")
                        
                        if wl.comment:
                            st.info(f"Comment: {wl.comment}")
                        
                        st.markdown("---")
        else:
            st.info("No wine lists downloaded yet")

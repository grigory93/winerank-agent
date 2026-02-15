"""Restaurants page - view and manage restaurants."""
import streamlit as st
import pandas as pd

from winerank.common.db import get_session
from winerank.common.models import Restaurant, MichelinDistinction, CrawlStatus


def render():
    """Render the Restaurants page."""
    st.title("🏪 Restaurants")
    
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
    
    # Query restaurants
    with get_session() as session:
        query = session.query(Restaurant)
        
        # Apply filters
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
        
        if restaurants:
            # Convert to DataFrame for display
            data = []
            for r in restaurants:
                data.append({
                    "ID": r.id,
                    "Name": r.name,
                    "Distinction": r.michelin_distinction.value if r.michelin_distinction else "N/A",
                    "City": r.city or "N/A",
                    "State": r.state or "N/A",
                    "Cuisine": r.cuisine or "N/A",
                    "Status": r.crawl_status.value,
                    "Has Wine List": "✓" if r.wine_list_url else "✗",
                    "Last Crawled": r.last_crawled_at.strftime("%Y-%m-%d") if r.last_crawled_at else "Never",
                })
            
            df = pd.DataFrame(data)
            
            # Display with selection
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Detail view for selected restaurant
            st.markdown("---")
            st.subheader("Restaurant Details")
            
            selected_id = st.number_input(
                "Select Restaurant ID to view details",
                min_value=1,
                max_value=max([r.id for r in restaurants]),
                value=restaurants[0].id if restaurants else 1,
                step=1,
            )
            
            selected = session.query(Restaurant).filter_by(id=selected_id).first()
            
            if selected:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Name:** {selected.name}")
                    st.write(f"**Distinction:** {selected.michelin_distinction.value if selected.michelin_distinction else 'N/A'}")
                    st.write(f"**City:** {selected.city or 'N/A'}")
                    st.write(f"**State:** {selected.state or 'N/A'}")
                    st.write(f"**Country:** {selected.country}")
                    st.write(f"**Cuisine:** {selected.cuisine or 'N/A'}")
                    st.write(f"**Price Range:** {selected.price_range or 'N/A'}")
                
                with col2:
                    st.write(f"**Status:** {selected.crawl_status.value}")
                    st.write(f"**Michelin URL:** {selected.michelin_url or 'N/A'}")
                    if selected.website_url:
                        st.write(f"**Website:** [{selected.website_url}]({selected.website_url})")
                    else:
                        st.write("**Website:** N/A")
                    if selected.wine_list_url:
                        st.write(f"**Wine List:** [{selected.wine_list_url}]({selected.wine_list_url})")
                    else:
                        st.write("**Wine List:** Not found")
                    st.write(f"**Last Crawled:** {selected.last_crawled_at or 'Never'}")
                
                if selected.comment:
                    st.write(f"**Comment:** {selected.comment}")
                
                # Show associated wine lists
                if selected.wine_lists:
                    st.markdown("---")
                    st.subheader("Wine Lists")
                    for wl in selected.wine_lists:
                        st.write(f"- {wl.list_name or 'Unnamed'} ({wl.wine_count} wines) - Downloaded: {wl.downloaded_at.strftime('%Y-%m-%d')}")
            else:
                st.warning(f"Restaurant with ID {selected_id} not found")
        else:
            st.info("No restaurants match the selected filters")

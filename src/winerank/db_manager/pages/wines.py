"""Wines page - browse and search wines."""
import streamlit as st
import pandas as pd

from winerank.common.db import get_session
from winerank.common.models import Wine, WineList, Restaurant


def render():
    """Render the Wines page."""
    st.title("🍷 Wines")
    
    # Filters
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        search_name = st.text_input("Search Name/Winery")
    
    with col2:
        filter_varietal = st.text_input("Varietal")
    
    with col3:
        filter_type = st.text_input("Wine Type")
    
    with col4:
        filter_country = st.text_input("Country")
    
    st.markdown("---")
    
    with get_session() as session:
        # Base query
        query = session.query(Wine).join(WineList).join(Restaurant)
        
        # Apply filters
        if search_name:
            query = query.filter(
                (Wine.name.ilike(f"%{search_name}%")) |
                (Wine.winery.ilike(f"%{search_name}%"))
            )
        
        if filter_varietal:
            query = query.filter(Wine.varietal.ilike(f"%{filter_varietal}%"))
        
        if filter_type:
            query = query.filter(Wine.wine_type.ilike(f"%{filter_type}%"))
        
        if filter_country:
            query = query.filter(Wine.country.ilike(f"%{filter_country}%"))
        
        # Get results
        wines = query.order_by(Wine.name).limit(100).all()
        
        st.write(f"**Showing {len(wines)} wines** (limited to 100 results)")
        
        if wines:
            # Convert to DataFrame
            data = []
            for w in wines:
                data.append({
                    "ID": w.id,
                    "Name": w.name,
                    "Winery": w.winery or "N/A",
                    "Varietal": w.varietal or "N/A",
                    "Type": w.wine_type or "N/A",
                    "Vintage": w.vintage or "N/A",
                    "Country": w.country or "N/A",
                    "Region": w.region or "N/A",
                    "Price": f"${w.price}" if w.price else "N/A",
                    "Restaurant": w.wine_list.restaurant.name,
                })
            
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Detail view
            st.markdown("---")
            st.subheader("Wine Details")
            
            selected_id = st.number_input(
                "Select Wine ID to view details",
                min_value=1,
                value=wines[0].id if wines else 1,
                step=1,
            )
            
            selected = session.query(Wine).filter_by(id=selected_id).first()
            
            if selected:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write(f"**Name:** {selected.name}")
                    st.write(f"**Winery:** {selected.winery or 'N/A'}")
                    st.write(f"**Varietal:** {selected.varietal or 'N/A'}")
                    st.write(f"**Type:** {selected.wine_type or 'N/A'}")
                    st.write(f"**Vintage:** {selected.vintage or 'N/A'}")
                
                with col2:
                    st.write(f"**Country:** {selected.country or 'N/A'}")
                    st.write(f"**Region:** {selected.region or 'N/A'}")
                    st.write(f"**Vineyard:** {selected.vineyard or 'N/A'}")
                    st.write(f"**Format:** {selected.format or 'N/A'}")
                    st.write(f"**Price:** ${selected.price}" if selected.price else "**Price:** N/A")
                
                st.write(f"**Restaurant:** {selected.wine_list.restaurant.name}")
                
                if selected.note:
                    st.write(f"**Note:** {selected.note}")
            else:
                st.warning(f"Wine with ID {selected_id} not found")
        else:
            st.info("No wines match the search criteria. Wines will appear here after running the Parser.")

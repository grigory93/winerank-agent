"""Sites of Record page - manage starting points for crawling."""
import streamlit as st

from winerank.common.db import get_session
from winerank.common.models import SiteOfRecord


def render():
    """Render the Sites of Record page."""
    st.title("Sites of Record")

    st.write("Sites of Record are starting points for the crawler to discover restaurants.")

    st.markdown("---")

    with get_session() as session:
        sites = session.query(SiteOfRecord).order_by(SiteOfRecord.created_at).all()

        if not sites:
            st.info("No sites of record configured. Run `winerank db init` to seed the Michelin Guide site.")
            return

        st.write(f"**Total: {len(sites)} site(s)**")

        for site in sites:
            with st.expander(site.site_name, expanded=True):
                col1, col2 = st.columns([2, 1])

                with col1:
                    st.write(f"**Name:** {site.site_name}")
                    st.write(f"**URL:** [{site.site_url}]({site.site_url})")

                    if site.navigational_notes:
                        st.write("**Navigational Notes:**")
                        st.code(site.navigational_notes, language=None)

                with col2:
                    st.write(f"**Created:** {site.created_at.strftime('%Y-%m-%d')}")
                    if site.last_visited_at:
                        st.write(f"**Last Visited:** {site.last_visited_at.strftime('%Y-%m-%d %H:%M')}")
                    else:
                        st.write("**Last Visited:** Never")

                    st.metric("Restaurants", len(site.restaurants))
                    st.metric("Jobs", len(site.jobs))

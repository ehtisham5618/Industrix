"""Presentation-only local quality alarm status; no siren controls in the UI."""
import requests
import streamlit as st

def quality_alarm_status(client):
    with st.expander('Quality severity alarms',expanded=False):
        try:data=client.request('GET','/qci3/status')
        except (requests.RequestException,ValueError):
            st.info('Quality alarm status is unavailable.');return
        st.caption(f"Policy: {data.get('policy_version')} · Active: {data.get('active',0)}")
        for event in data.get('events',[])[:20]:
            message=f"{event['source_id']} / {event['event_id']} · {event['state'].upper()} · Siren delivery: {event['delivery']}"
            if event['state']=='critical':st.error(message)
            elif event['state']=='warning':st.warning(message)
            else:st.info(message)
            st.caption(f"Last transition: {event['last_transition']}")

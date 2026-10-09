"""Minimal presentation of actual edge/cloud state, without cloud controls."""
import requests
import streamlit as st

def edge_health_status(client):
    with st.expander('Edge health and optional cloud synchronization',expanded=True):
        try:data=client.request('GET','/edge/status')
        except (requests.RequestException,ValueError):st.warning('Edge telemetry is unavailable.');return
        cloud=data['cloud'];state=cloud['status']
        if state=='DISABLED':st.info('LOCAL ONLY — CLOUD DISABLED')
        elif state in ('OFFLINE','DEGRADED'):st.warning('LOCAL MODE — CLOUD SYNC PENDING')
        elif state=='RECOVERING':st.info('CLOUD RESTORED — SYNCHRONIZING')
        elif state=='ONLINE':st.success('Cloud synchronization available')
        else:st.info('Cloud connectivity has not been verified yet.')
        r=data['resources'];spool=data['spool']
        st.caption(f"Outbound permissions: metrics {data['outbound_telemetry_permitted']} · event summaries {data['outbound_event_summaries_permitted']} · images stay local")
        st.caption(f"Edge: {data['edge_status']} · Mode: {cloud['mode']} · Pending: {spool['pending']+spool['in_flight']} · Inference: {data['inference']['status']}")
        values=st.columns(3)
        values[0].metric('System CPU','Unavailable' if r['cpu_percent'] is None else f"{r['cpu_percent']:.1f}%")
        values[1].metric('System RAM','Unavailable' if r['ram_percent'] is None else f"{r['ram_percent']:.1f}%")
        values[2].metric('Process RSS','Unavailable' if r['process_rss_mb'] is None else f"{r['process_rss_mb']:.1f} MiB")

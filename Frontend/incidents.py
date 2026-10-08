"""Local incident history/export presentation; no SQL or PDF layout here."""
import time
import os
import json
from pathlib import Path
from urllib.parse import quote
import requests
import streamlit as st

@st.fragment
def incident_history(client):
    st.subheader('Incident History')
    st.caption('Confirmed incidents are stored locally. PDF export generates a fresh internal audit record.')
    if st.button('Refresh incident history',key='refresh-incidents'):
        st.session_state.pop('incident_export_pdf',None)
    try:
        payload=client.request('GET','/incidents',params={'limit':100})
        rows=payload.get('incidents',[])+payload.get('quality_incidents',[])
    except requests.RequestException as exc:
        st.warning(f'Incident history unavailable: {exc}');return
    if payload.get('logging_failures'):
        st.warning(f"Incident storage recorded {payload['logging_failures']} write/update failure(s). Review backend logs and evidence status.")
    if not rows:
        st.info('No formally confirmed incidents have been logged. Candidate detections are excluded.');return
    st.dataframe([dict(Incident=r['incident_id'],UTC=r['timestamp'],Camera=r['camera_location'],Class=r['class_name'],
        Severity=r['severity'].upper(),Confidence=f"{r['confidence']*100:.1f}%",Status=r['status'],Evidence=r['snapshot_status'],
        Sample=bool(r['is_sample']) if r['is_sample'] is not None else 'Not recorded') for r in rows],hide_index=True,width='stretch')
    selected=st.selectbox('Select incident',[r['incident_id'] for r in rows])
    row=next(r for r in rows if r['incident_id']==selected);path='/incidents/'+quote(selected,safe='')
    evidence=st.expander('Evidence snapshot',expanded=False,key='incident-evidence',on_change='rerun')
    if evidence.open and not selected.startswith('QCI3-'):
        with evidence:
            try:st.image(client.binary('GET',path+'/snapshot').content,caption='Local unannotated cropped evidence',width=400)
            except requests.RequestException:st.caption('Evidence image unavailable. Export can still include the incident metadata.')
    if row['is_sample']:st.info('SAMPLE / DEMONSTRATION - prerecorded or controlled scenario, not an operational incident.')
    key=(client.base_url,selected,row['updated_at'],'qci5-report-v1')
    if st.session_state.get('incident_export_key')!=key:
        st.session_state.pop('incident_export_pdf',None)
    if st.button('Export Incident PDF',type='primary'):
        began=time.perf_counter()
        try:
            response=client.binary('POST',path+'/export')
            if not response.content.startswith(b'%PDF-'):raise requests.RequestException('Backend did not return a valid PDF')
            st.session_state.incident_export_pdf=response.content;st.session_state.incident_export_key=key
            st.session_state.incident_export_ms=(time.perf_counter()-began)*1000
            st.session_state.incident_pdf_filename=response.headers.get('Content-Disposition','').split('filename="')[-1].rstrip('"')
            st.session_state.incident_pdf_generation_ms=float(response.headers.get('X-PDF-Generation-Ms','nan'))
            ready_at=time.time()
            # Validation-only local timing journal. Actual browser click time is
            # correlated outside the product UI; no epoch/debug data is shown.
            if os.getenv('INCIDENT_UI_TIMINGS_PATH'):
                try:
                    with Path(os.environ['INCIDENT_UI_TIMINGS_PATH']).open('a',encoding='utf-8') as journal:
                        journal.write(json.dumps(dict(incident_id=selected,bytes_ready_at=ready_at,
                            request_ms=st.session_state.incident_export_ms,generation_ms=st.session_state.incident_pdf_generation_ms))+'\n')
                except OSError:pass  # Optional instrumentation cannot break export.
        except requests.RequestException as exc:
            st.session_state.pop('incident_export_pdf',None);st.error(f'PDF export failed: {exc}')
    if st.session_state.get('incident_export_pdf') and st.session_state.get('incident_export_key')==key:
        st.caption(f"Fresh PDF generation: {st.session_state.incident_pdf_generation_ms:.3f} ms. Export request to bytes ready: {st.session_state.incident_export_ms:.3f} ms.")
        st.download_button('Download Incident PDF',data=st.session_state.incident_export_pdf,
            file_name=st.session_state.incident_pdf_filename,mime='application/pdf',on_click='ignore')

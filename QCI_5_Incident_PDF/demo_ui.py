"""Reviewer harness for the actual existing incident-history component, not a second UI."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import streamlit as st
from Frontend.api_client import APIClient
from Frontend.incidents import incident_history
st.set_page_config(page_title='IndusriX incident PDF verification',layout='wide')
st.title('IndusriX local incident PDF review')
st.caption('QCI-3 software research demonstration; no factory incident asserted. Existing incident-history component.')
incident_history(APIClient('http://127.0.0.1:8765'))

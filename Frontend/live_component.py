"""Local component assets; no external scripts or model dependencies."""
from pathlib import Path
import streamlit.components.v1 as components

_console = components.declare_component('industrial_live_console',path=str(Path(__file__).parent/'components/live_console'))

def live_console(backend_url):
    return _console(backend_url=backend_url,key='industrial-live-console',default=None)

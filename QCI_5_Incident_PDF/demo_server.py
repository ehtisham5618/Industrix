"""Isolated reviewer host using the existing router, real records and local-only assets."""
import os
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from Backend.incidents.repository import IncidentRepository
from Backend.incidents import api
from .adapter import ROOT
from QCI_3_Severity_IoT.offline import loopback_only

os.environ['QCI5_CONFIG']=str(ROOT/'QCI_5_Incident_PDF/runtime/sample_config.json')
repository=IncidentRepository(ROOT/'QCI_5_Incident_PDF/runtime/ui_legacy.db',ROOT/'QCI_5_Incident_PDF/runtime/snapshots')
api.get_logger=lambda:SimpleNamespace(repository=repository,failures=0,last_error=None)
app=FastAPI();app.include_router(api.router)

if __name__=='__main__':
    import uvicorn
    # External TCP prohibited for the complete live local API process.
    with loopback_only() as attempts:
        uvicorn.run(app,host='127.0.0.1',port=int(os.getenv('QCI5_DEMO_API_PORT','8765')),log_level='warning')
        print('External TCP attempts blocked:',len(attempts))

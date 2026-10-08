"""Compatibility entry point; CLI/API use the same QCI-5 ReportLab service."""
import time
from QCI_5_Incident_PDF.adapter import Adapter
from QCI_5_Incident_PDF.service import PDFService

def export_pdf(repository,incident_id):
    began=time.perf_counter()
    adapter=Adapter(repository)
    report=adapter.load(incident_id)
    data,_,_,_=PDFService(adapter).render(report)
    return data,time.perf_counter()-began

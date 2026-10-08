import logging
import time
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response
from .service import get_logger
from .repository import validate_id
from QCI_5_Incident_PDF.adapter import Adapter, configuration, identity
from QCI_5_Incident_PDF.service import PDFService, filename
from QCI_5_Incident_PDF.contracts import Telemetry

router=APIRouter(prefix='/incidents',tags=['Local incident audit'])

def report_telemetry():
    # Read an already-running QCI-4 monitor; never start a cloud worker for export.
    from QCI_4_Edge_Telemetry import api
    with api._LOCK:
        current=api._INSTANCE
        if current is None:raise ValueError('Telemetry not running')
        with current.collector.lock:
            snapshot=current.collector.latest
            if snapshot is None:raise ValueError('Telemetry not sampled')
            snapshot=snapshot.model_copy(deep=True)
    return Telemetry(timestamp=snapshot.timestamp,edge_status=snapshot.edge_status.value,
        cloud_status=snapshot.cloud.status.value,mode=snapshot.cloud.mode.value,pending=snapshot.spool.pending,
        cpu_percent=snapshot.resources.cpu_percent,process_rss_mb=snapshot.resources.process_rss_mb)

def report_service():
    try:legacy=repository()
    except HTTPException:legacy=None
    return PDFService(Adapter(legacy,configuration(),telemetry=report_telemetry))

def repository():
    try:return get_logger().repository
    except Exception as exc:raise HTTPException(503,'Local incident storage unavailable') from exc

@router.get('')
def list_incidents(limit:int=Query(100,ge=1,le=200)):
    try:
        rows=repository().list(limit);logger=get_logger()
        quality=Adapter(config=configuration()).list_quality(limit)
        return dict(incidents=rows,quality_incidents=quality,logging_failures=logger.failures,last_error=logger.last_error)
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Local incident database read failed') from exc

def get_incident(incident_id):
    try:
        if identity(incident_id):return report_service().adapter.load(incident_id).model_dump(mode='json',exclude={'evidence':{'__all__':{'path'}}})
        return repository().get(validate_id(incident_id))
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except KeyError as exc:raise HTTPException(404,'Incident not found') from exc
    except HTTPException:raise
    except Exception as exc:raise HTTPException(503,'Local incident database read failed') from exc

@router.get('/{incident_id}')
def incident_detail(incident_id:str):return get_incident(incident_id)

@router.get('/{incident_id}/snapshot')
def incident_snapshot(incident_id:str):
    try:
        if identity(incident_id):raise HTTPException(404,'Quality evidence is available in the report only')
    except ValueError as exc:raise HTTPException(422,'Invalid incident ID') from exc
    row=get_incident(incident_id)
    try:
        path=repository().snapshot_file(row)
        if path is None or not path.is_file():raise FileNotFoundError()
        return Response(path.read_bytes(),media_type='image/jpeg',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    except (OSError,ValueError) as exc:raise HTTPException(404,'Evidence image unavailable') from exc

@router.post('/{incident_id}/export')
def incident_export(incident_id:str):
    try:
        result=report_service().generate(incident_id)
        if result.status!='SUCCESS':
            code={'NOT_FOUND':404,'INVALID_INPUT':422,'STORAGE_UNAVAILABLE':503,'EXPORT_FAILED':503}[result.error]
            raise HTTPException(code,{'status':'FAILED','incident_id':incident_id,'error':result.error,'report_version':result.report_version})
        from pathlib import Path
        data=Path(result.output_path).read_bytes()
        return Response(data,media_type='application/pdf',headers={
            'X-PDF-Generation-Ms':f'{result.latency_ms:.6f}','X-Report-Version':result.report_version,
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Content-Disposition':f'attachment; filename="{filename(incident_id)}"'})
    except HTTPException:raise
    except Exception as exc:
        logging.getLogger(__name__).error('PDF_EXPORT_FAILED incident_id=%s error_type=%s',incident_id,type(exc).__name__)
        raise HTTPException(503,'Local PDF generation failed') from exc

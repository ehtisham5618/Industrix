"""Cached health endpoints and application-owned sampler/sync lifecycle."""
import logging
import os
from pathlib import Path
import sqlite3
import threading
from fastapi import APIRouter,HTTPException,Query
from .contracts import Config,Snapshot,parse_config
from .spool import Spool
from .cloud import SyncWorker
from .collector import Collector

LOGGER=logging.getLogger('qci4')
router=APIRouter(prefix='/edge',tags=['Edge telemetry and optional sync'])
_INSTANCE=None;_LOCK=threading.RLock()

class EdgeService:
    def __init__(self,config,tracker=None):
        self.config=config;self.spool=Spool(config);self.worker=SyncWorker(self.spool)
        self.collector=Collector(config,self.spool,self.worker,tracker=tracker)
    def start(self):self.collector.start();self.worker.start()
    def stop(self):
        try:self.collector.stop()
        finally:self.worker.stop()

def configuration():
    path=os.getenv('QCI4_CONFIG')
    if path:
        p=Path(path)
        if p.stat().st_size>65536:raise ValueError('Configuration exceeds 64 KiB')
        config=parse_config(p.read_text(encoding='utf-8'))
    else:
        config=Config()
        # Observe the actual QCI-3 configured storage without starting its worker.
        qci3=os.getenv('QCI3_CONFIG')
        if qci3:
            from QCI_3_Severity_IoT.contracts import parse_config as parse_alarm_config
            p=Path(qci3)
            if p.stat().st_size>65536:raise ValueError('Alarm config exceeds bound')
            config.alerts_database=parse_alarm_config(p.read_text(encoding='utf-8')).database
    values=config.model_dump()
    if 'INDUSRIX_CLOUD_ENABLED' in os.environ:
        flag=os.environ['INDUSRIX_CLOUD_ENABLED'].lower()
        if flag not in ('true','false'):raise ValueError('Cloud enabled must be true/false')
        values['cloud_enabled']=flag=='true'
    if 'INDUSRIX_CLOUD_URL' in os.environ:values['cloud_base_url']=os.environ['INDUSRIX_CLOUD_URL']
    return Config.model_validate(values)

def service():
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:_INSTANCE=EdgeService(configuration())
        return _INSTANCE

def startup():
    try:service().start()
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
        # Broken optional monitoring configuration must not take local inference down.
        LOGGER.error('QCI4_MONITOR_UNAVAILABLE error_type=%s',type(exc).__name__)

def shutdown():
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is not None:
            _INSTANCE.stop();_INSTANCE=None

@router.get('/status',response_model=Snapshot)
def status():
    try:return service().collector.status()
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:raise HTTPException(503,'Local telemetry unavailable; local AI remains independent') from exc

@router.get('/history')
def history(limit:int=Query(20,ge=1,le=100)):
    collector=service().collector
    with collector.lock:return [s.model_dump(mode='json') for s in list(collector.history)[-limit:]]

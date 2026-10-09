"""Small API bridge; QCI-2 inference remains owned by its existing caller."""
import threading
import json
import os
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.routing import APIRoute
from .contracts import Config,Event,Resolve,Status,parse_config
from .engine import AlarmEngine,CapacityError,ConflictError
from .webhook import WebhookWorker

class BoundedRoute(APIRoute):
    def get_route_handler(self):
        original=super().get_route_handler()
        async def handle(request):
            if request.method=='POST':
                body=bytearray()
                async for chunk in request.stream():
                    if len(body)+len(chunk)>65536:raise HTTPException(413,'Alarm request exceeds 64 KiB')
                    body.extend(chunk)
                request._body=bytes(body)
            return await original(request)
        return handle

router=APIRouter(prefix='/qci3',tags=['Local quality alarms'],route_class=BoundedRoute)

_INSTANCE=None
_SERVICE_LOCK=threading.RLock()

def _create_service():
    path=os.getenv('QCI3_CONFIG')
    if path:
        p=Path(path)
        if p.stat().st_size>65536:raise ValueError('Alarm configuration exceeds 64 KiB')
        config=parse_config(p.read_text(encoding='utf-8'))
    else:config=Config()
    endpoint=os.getenv('QCI3_SIREN_URL')
    if endpoint:
        values=config.model_dump();values['webhook']['url']=endpoint;config=Config.model_validate(values)
    engine=AlarmEngine(config);worker=WebhookWorker(engine);worker.start();return engine,worker

def service():
    global _INSTANCE
    # Unlike lru_cache, this prevents concurrent first requests starting orphan workers.
    with _SERVICE_LOCK:
        if _INSTANCE is None:_INSTANCE=_create_service()
        return _INSTANCE

def shutdown():
    global _INSTANCE
    with _SERVICE_LOCK:
        if _INSTANCE is not None:
            _INSTANCE[1].stop();_INSTANCE=None

@router.get('/status')
def status():
    engine,worker=service();result=engine.snapshot()
    result['worker_running']=bool(worker and worker.thread and worker.thread.is_alive())
    return result

@router.post('/events',response_model=Status)
def events(event:Event):
    try:return service()[0].process(event)
    except CapacityError as exc:raise HTTPException(503,str(exc)) from exc
    except ConflictError as exc:raise HTTPException(409,str(exc)) from exc

@router.post('/resolve',response_model=Status)
def resolve(request:Resolve):
    try:return service()[0].resolve(request)
    except ConflictError as exc:raise HTTPException(409,str(exc)) from exc

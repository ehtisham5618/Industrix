"""Application-specific health/ack checks with bounded sockets and managed retries."""
from __future__ import annotations
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import http.client
import json
import os
import random
import sqlite3
import ssl
import threading
import time
from urllib.parse import urlsplit
from .contracts import CloudHealth,CloudStatus,Mode,SyncState,utc

@dataclass(frozen=True)
class HttpResult:
    status:int|None
    data:object
    error:str|None
    latency_ms:float
    retry_after:float|None=None

class CloudClient:
    def __init__(self,config):self.config=config

    def request(self,method,path,body=None,key=None):
        c=self.config
        if not c.cloud_enabled:return HttpResult(None,None,'cloud_disabled',0)
        u=urlsplit(c.cloud_base_url);started=time.monotonic();deadline=started+c.request_timeout_seconds
        token=os.getenv(c.token_environment)
        if token and (len(token)>4096 or '\r' in token or '\n' in token):return HttpResult(None,None,'invalid_authentication_configuration',0)
        headers={'Accept':'application/json','Content-Type':'application/json','Connection':'close'}
        if token:headers['Authorization']='Bearer '+token
        if key:headers['Idempotency-Key']=key
        connection=(http.client.HTTPSConnection(u.hostname,u.port,timeout=c.request_timeout_seconds,context=ssl.create_default_context())
            if u.scheme=='https' else http.client.HTTPConnection(u.hostname,u.port,timeout=c.request_timeout_seconds))
        try:
            connection.connect()
            if time.monotonic()>=deadline:raise TimeoutError('Connection deadline exceeded')
            connection.sock.settimeout(deadline-time.monotonic())
            connection.request(method,path,body=json.dumps(body,separators=(',',':')).encode() if body is not None else None,headers=headers)
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Request deadline exceeded')
            stream=connection.sock
            def receive(size):
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Response deadline exceeded')
                stream.settimeout(remaining)
                data=stream.recv(size)
                if not data:raise OSError('Incomplete HTTP response')
                return data
            # Parse a bounded header under the SAME absolute deadline. A server
            # trickling headers cannot reset a per-read timeout indefinitely.
            header=bytearray()
            while not header.endswith(b'\r\n\r\n'):
                if len(header)>=8192:return HttpResult(None,None,'oversized_response_headers',(time.monotonic()-started)*1000)
                header.extend(receive(1))
            lines=header.decode('iso-8859-1').split('\r\n');parts=lines[0].split(' ',2)
            if len(parts)<2 or parts[0] not in ('HTTP/1.0','HTTP/1.1') or not parts[1].isdigit():
                return HttpResult(None,None,'malformed_response_headers',(time.monotonic()-started)*1000)
            status=int(parts[1]);response_headers={}
            for line in lines[1:]:
                if not line:continue
                if ':' not in line:return HttpResult(status,None,'malformed_response_headers',(time.monotonic()-started)*1000)
                name,value=line.split(':',1);name=name.strip().lower()
                if name in response_headers:return HttpResult(status,None,'duplicate_response_header',(time.monotonic()-started)*1000)
                response_headers[name]=value.strip()
            length=response_headers.get('content-length')
            if 'transfer-encoding' in response_headers or length is None or not length.isdigit():
                return HttpResult(status,None,'bounded_content_length_required',(time.monotonic()-started)*1000)
            length=int(length)
            if length>8192:return HttpResult(status,None,'oversized_response',(time.monotonic()-started)*1000)
            raw=bytearray()
            while len(raw)<length:raw.extend(receive(length-len(raw)))
            latency=(time.monotonic()-started)*1000
            try:data=json.loads(raw)
            except (ValueError,UnicodeError):data=None
            retry=None
            value=response_headers.get('retry-after')
            if value and len(value)<128:
                try:
                    retry=float(value) if value.strip().isdigit() else parsedate_to_datetime(value).timestamp()-time.time()
                    retry=min(c.backoff_max_seconds,max(0,retry))
                except (ValueError,TypeError,OverflowError):retry=None
            return HttpResult(status,data,None if data is not None else 'malformed_response',latency,retry)
        except (OSError,http.client.HTTPException,TimeoutError,ValueError):
            return HttpResult(None,None,'transport_outcome_unknown',(time.monotonic()-started)*1000)
        finally:connection.close()

    def health(self):
        result=self.request('GET',self.config.health_path)
        valid=result.status==200 and isinstance(result.data,dict) and result.data.get('status')=='ok' and result.data.get('service')==self.config.expected_service
        return valid,result

    def send(self,row):
        body={'schema_version':'qci4-sync-v1','item_id':row['id'],'dedupe_key':row['dedupe'],
            'payload_sha256':row['digest'],'payload':json.loads(row['payload'])}
        result=self.request('POST',self.config.sync_path,body,row['dedupe'])
        ack=result.data
        valid=result.status is not None and 200<=result.status<300 and isinstance(ack,dict) and ack.get('accepted') is True and all(
            ack.get(field)==body[field] for field in ('item_id','dedupe_key','payload_sha256'))
        return valid,result

class SyncWorker:
    def __init__(self,spool,client=None,clock=time.time,random_value=None):
        self.spool=spool;self.config=spool.config;self.client=client or CloudClient(self.config)
        self.clock=clock;self.random_value=random_value or random.SystemRandom().random;self.lock=threading.RLock();self.tick_lock=threading.Lock()
        self.stop_event=threading.Event();self.thread=None;self.next_health=0.;self.next_send=0.;self.last_health_ok=False
        last=spool.get_meta('last_successful_sync')
        self.current=CloudHealth(status=CloudStatus.UNKNOWN if self.config.cloud_enabled else CloudStatus.DISABLED,
            health_check_status='UNKNOWN' if self.config.cloud_enabled else 'DISABLED',last_successful_sync=utc(float(last)) if last else None)

    def snapshot(self):
        with self.lock:return self.current.model_copy(deep=True)

    def backoff(self,attempt,retry_after=None):
        c=self.config;base=min(c.backoff_max_seconds,c.backoff_base_seconds*2**min(attempt-1,20))
        delay=min(c.backoff_max_seconds,base*(1+c.jitter_fraction*self.random_value()))
        return max(delay,retry_after or 0)

    def _failure(self,error,result,health=False):
        with self.lock:
            self.current.failures=min(10**12,self.current.failures+1)
            self.current.status=CloudStatus.OFFLINE if self.current.failures>=self.config.offline_after_failures and not self.last_health_ok else CloudStatus.DEGRADED
            self.current.mode=Mode.LOCAL_ONLY;self.current.last_error=error
            self.current.last_operation_latency_ms=result.latency_ms
            if health:self.current.health_check_status='FAILED'
        self.spool.log('CLOUD_OFFLINE' if self.current.status==CloudStatus.OFFLINE else 'FAILOVER_ACTIVATED',
            cloud_status=self.current.status.value,error_category=error,latency_ms=result.latency_ms)

    def tick(self,force_health=False):
        if not self.config.cloud_enabled:return False
        with self.tick_lock:
            now=self.clock()
            if force_health or now>=self.next_health:
                valid,result=self.client.health();self.last_health_ok=valid
                with self.lock:self.current.checked_at=utc(now)
                if valid:
                    with self.lock:
                        self.current.health_check_status='ONLINE';self.current.last_operation_latency_ms=result.latency_ms
                        # A passing health check does not erase an unresolved upload failure.
                        if self.current.status!=CloudStatus.ONLINE and self.current.sync_status not in (SyncState.FAILED_PERMANENT,SyncState.FAILED_RETRYABLE,SyncState.DELIVERY_UNKNOWN):
                            self.current.status=CloudStatus.RECOVERING;self.current.mode=Mode.RECOVERING
                    self.next_health=now+self.config.health_interval_seconds
                else:
                    self._failure(result.error or 'health_contract_failed',result,health=True)
                    self.next_health=now+max(self.config.health_interval_seconds,self.backoff(self.current.failures))
                with self.lock:self.current.next_health_check_at=utc(self.next_health)
            if not self.last_health_ok:return False
            if now<self.next_send:return False
            row=self.spool.claim()
            if row is None:
                stats=self.spool.stats()
                with self.lock:
                    if stats.pending+stats.in_flight==0 and self.current.sync_status not in (SyncState.FAILED_PERMANENT,SyncState.DELIVERY_UNKNOWN,SyncState.FAILED_RETRYABLE) and stats.failed_permanent+stats.unknown==0:
                        recovered=self.current.status!=CloudStatus.ONLINE
                        self.current.status=CloudStatus.ONLINE;self.current.mode=Mode.CONNECTED;self.current.failures=0;self.current.last_error=None
                        if recovered:self.spool.log('CLOUD_ONLINE',queue_depth=0)
                return False
            valid,result=self.client.send(row);attempt=row['attempts']
            if valid:
                state=SyncState.DELIVERED;error=None
            elif result.status is not None and 400<=result.status<500 and result.status!=429:
                state=SyncState.FAILED_PERMANENT;error='http_client_error'
            elif result.status is not None and 300<=result.status<400:
                state=SyncState.FAILED_PERMANENT;error='redirect_not_followed'
            else:
                state=SyncState.FAILED_RETRYABLE if attempt<self.config.attempts else SyncState.DELIVERY_UNKNOWN if result.status is None or (result.status and 200<=result.status<300) else SyncState.FAILED_PERMANENT
                error=result.error or ('rate_limited' if result.status==429 else 'http_server_error' if result.status and result.status>=500 else 'ack_contract_failed')
            due=self.clock()+self.backoff(attempt,result.retry_after)
            self.spool.complete(row,state,error,result.status,due)
            with self.lock:
                self.current.sync_status=state;self.current.last_operation_latency_ms=result.latency_ms
                if valid:
                    was_online=self.current.status==CloudStatus.ONLINE
                    self.current.last_successful_sync=utc(self.clock());self.current.failures=0;self.current.last_error=None
                    stats=self.spool.stats()
                    self.current.status=CloudStatus.DEGRADED if stats.failed_permanent+stats.unknown else CloudStatus.ONLINE if was_online else CloudStatus.RECOVERING if stats.pending+stats.in_flight else CloudStatus.ONLINE
                    self.current.mode=Mode.LOCAL_ONLY if self.current.status==CloudStatus.DEGRADED else Mode.RECOVERING if self.current.status==CloudStatus.RECOVERING else Mode.CONNECTED
                    if self.current.status==CloudStatus.ONLINE and not was_online:self.spool.log('CLOUD_RECOVERED',queue_depth=0)
            if not valid:self._failure(error,result)
            self.next_send=self.clock()+max(1/self.config.replay_items_per_second,(result.retry_after or 0) if not valid else 0)
            return True

    def _run(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except (OSError,sqlite3.Error,RuntimeError,ValueError):
                with self.lock:self.current.status=CloudStatus.DEGRADED;self.current.mode=Mode.LOCAL_ONLY;self.current.last_error='local_sync_worker_error'
            self.stop_event.wait(.05)

    def start(self):
        if not self.config.cloud_enabled:return
        with self.lock:
            if self.thread and self.thread.is_alive():return
            self.stop_event.clear();self.thread=threading.Thread(target=self._run,name='qci4-sync-worker',daemon=False);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2*self.config.request_timeout_seconds+3)
        if self.thread and self.thread.is_alive():raise RuntimeError('Sync worker failed to stop within configured bound')

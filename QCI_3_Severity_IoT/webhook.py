"""Durable bounded retries on one managed worker; explicit receiver acknowledgement."""
from __future__ import annotations
import http.client
import json
import os
import socket
import sqlite3
import threading
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit
from .contracts import Delivery,Status

class WebhookWorker:
    def __init__(self,engine):
        self.engine=engine;self.config=engine.config.webhook
        self.stop_event=threading.Event();self.thread=None
        self.lock=threading.Lock()

    def start(self):
        if self.config.enabled and (not self.thread or not self.thread.is_alive()):
            self.stop_event.clear();self.thread=threading.Thread(target=self._loop,name='qci3-outbox',daemon=False);self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=self.config.timeout_seconds+2)
        if self.thread and self.thread.is_alive():raise RuntimeError('Webhook worker did not shut down')

    def _loop(self):
        while not self.stop_event.is_set():
            try:self.run_once()
            except (OSError,RuntimeError,sqlite3.Error):
                # No state is falsely marked delivered on local storage failure.
                self.stop_event.wait(.25)
            self.stop_event.wait(.025)

    def _send(self,payload):
        c=self.config;u=urlsplit(c.url);deadline=time.monotonic()+c.timeout_seconds
        connection=(http.client.HTTPSConnection if u.scheme=='https' else http.client.HTTPConnection)(
            u.hostname,u.port,timeout=c.timeout_seconds)
        try:
            headers={'Content-Type':'application/json','Idempotency-Key':payload['delivery_id']}
            token=os.environ.get(c.token_environment)
            if token and (len(token)>4096 or '\r' in token or '\n' in token):
                return Delivery.FAILED,None,'invalid_authentication_configuration',False
            if token:headers['Authorization']='Bearer '+token
            connection.connect()
            if time.monotonic()>=deadline:raise TimeoutError('Connection deadline exceeded')
            connection.sock.settimeout(max(.001,deadline-time.monotonic()))
            connection.request('POST',u.path or '/',body=json.dumps(payload).encode(),headers=headers)
            connection.sock.settimeout(max(.001,deadline-time.monotonic()))
            response=connection.getresponse();code=response.status
            response_socket=connection.sock
            if response_socket is None and response.fp is not None:
                response_socket=getattr(getattr(response.fp,'raw',None),'_sock',None)
            # Read one bounded byte at a time with an absolute deadline: trickled replies
            # cannot reset a per-read timeout indefinitely or allocate arbitrary bodies.
            body=bytearray()
            while len(body)<=8192:
                if response.isclosed():break
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Webhook deadline exceeded')
                if response_socket:response_socket.settimeout(remaining)
                chunk=response.read(1)
                if not chunk:break
                body.extend(chunk)
            if len(body)>8192:return Delivery.DELIVERY_UNKNOWN,code,'oversized_response',False
            if 200<=code<300:
                try:ack=json.loads(body)
                except (ValueError,UnicodeError):ack=None
                valid=isinstance(ack,dict) and ack.get('delivery_id')==payload['delivery_id'] and ack.get('acknowledged') is True
                return (Delivery.ACKNOWLEDGED if valid else Delivery.DELIVERY_UNKNOWN),code,('receiver_acknowledged' if valid else 'missing_matching_ack'),False
            if 400<=code<500:return Delivery.FAILED,code,'http_client_error',False
            if 500<=code<600:return Delivery.PENDING,code,'http_server_error',True
            return Delivery.DELIVERY_UNKNOWN,code,'redirect_or_unexpected_status',False
        except (OSError,http.client.HTTPException,TimeoutError):
            # No exception text, URL, payload or authentication data enters logs/status.
            return Delivery.DELIVERY_UNKNOWN,None,'transport_outcome_unknown',True
        finally:connection.close()

    def run_once(self):
        if not self.config.enabled:return False
        with self.lock:
            now=self.engine.clock()
            with self.engine.connect() as db:
                expired=db.execute("SELECT * FROM qci3_outbox WHERE state='IN_FLIGHT' AND lease<=?",(now,)).fetchall()
                for row in expired:
                    state='PENDING' if self.config.receiver_idempotent and row['attempts']<self.config.attempts else 'DELIVERY_UNKNOWN'
                    db.execute('UPDATE qci3_outbox SET state=?,due=?,last_error=? WHERE id=?',
                        (state,now,'expired_dispatch_lease',row['id']))
                    if state!='PENDING':self._update_status(db,row,state)
                row=db.execute("SELECT * FROM qci3_outbox WHERE state='PENDING' AND due<=? ORDER BY due,id LIMIT 1",(now,)).fetchone()
                if not row:return False
                if row['attempts']>=self.config.attempts:
                    db.execute("UPDATE qci3_outbox SET state='DELIVERY_UNKNOWN' WHERE id=?",(row['id'],))
                    self._update_status(db,row,'DELIVERY_UNKNOWN');return True
                db.execute("UPDATE qci3_outbox SET state='IN_FLIGHT',lease=?,attempts=attempts+1 WHERE id=?",
                    (now+self.config.timeout_seconds+2,row['id']))
            # Network work is outside the SQLite transaction and local engine path.
            result,code,error,retry=self._send(json.loads(row['payload']))
            attempt=row['attempts']+1
            if retry and self.config.receiver_idempotent and attempt<self.config.attempts:
                result=Delivery.PENDING
            elif result==Delivery.PENDING:result=Delivery.FAILED
            with self.engine.connect() as db:
                # Resolution during dispatch never changes the resolved lifecycle.
                event=db.execute('SELECT resolved FROM qci3_events WHERE source=? AND event=?',(row['source'],row['event'])).fetchone()
                if event and event[0] and result==Delivery.PENDING:result=Delivery.DELIVERY_UNKNOWN
                db.execute('UPDATE qci3_outbox SET state=?,due=?,lease=0,last_error=?,last_http_status=? WHERE id=?',
                    (result.value,self.engine.clock()+self.config.backoff_seconds*2**(attempt-1),error,code,row['id']))
                self._update_status(db,row,result.value,attempt,code,error)
            return True

    def _update_status(self,db,row,state,attempt=None,code=None,error=None):
        item=db.execute('SELECT status FROM qci3_events WHERE source=? AND event=?',(row['source'],row['event'])).fetchone()
        if item:
            status=Status.model_validate_json(item[0]);status.delivery=Delivery(state)
            if attempt is not None:status.delivery_attempts=attempt
            status.last_http_status=code;status.last_delivery_error=error
            db.execute('UPDATE qci3_events SET status=? WHERE source=? AND event=?',
                (status.model_dump_json(),row['source'],row['event']))
            # Record delivery separately from state changes; never fabricate a new transition.
            db.execute('INSERT INTO qci3_audit(source,event,time,before_state,after_state,detail) VALUES(?,?,?,?,?,?)',
                (row['source'],row['event'],datetime.fromtimestamp(self.engine.clock(),timezone.utc).isoformat(),
                    status.state.value,status.state.value,json.dumps({'delivery':state,'delivery_id':row['id'],
                    'attempt':attempt,'http_status':code,'error_category':error})))
            db.execute('DELETE FROM qci3_audit WHERE id NOT IN (SELECT id FROM qci3_audit ORDER BY id DESC LIMIT ?)',
                (self.engine.config.audit_capacity,))

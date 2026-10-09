"""Bounded prefixed SQLite spool, receipts and structured audit; existing tables preserved."""
from __future__ import annotations
from contextlib import closing,contextmanager,nullcontext
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from pydantic import TypeAdapter
from Backend.incidents.repository import ROOT,local_storage_path
from .contracts import Config,Payload,SyncItem,SyncState,SpoolStats,utc

ADAPTER=TypeAdapter(Payload)
ACTIVE=('PENDING','IN_FLIGHT','FAILED_RETRYABLE')
class OverflowError(RuntimeError):pass
class DedupeConflict(ValueError):pass

SCHEMA='''
CREATE TABLE IF NOT EXISTS qci4_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qci4_spool(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,dedupe TEXT NOT NULL UNIQUE,
 created REAL NOT NULL,kind TEXT NOT NULL,activation TEXT,priority INTEGER NOT NULL,
 payload TEXT NOT NULL,bytes INTEGER NOT NULL,digest TEXT NOT NULL,state TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,last_attempt REAL,due REAL NOT NULL,lease REAL NOT NULL DEFAULT 0,
 last_error TEXT,last_http_status INTEGER);
CREATE INDEX IF NOT EXISTS qci4_spool_dispatch ON qci4_spool(state,due,priority,seq);
CREATE INDEX IF NOT EXISTS qci4_spool_activation ON qci4_spool(activation,seq);
CREATE TABLE IF NOT EXISTS qci4_receipts(dedupe TEXT PRIMARY KEY,digest TEXT NOT NULL,id TEXT NOT NULL,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS qci4_log(id INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT NOT NULL,code TEXT NOT NULL,fields TEXT NOT NULL);
'''

class Spool:
    def __init__(self,config:Config,clock=time.time):
        self.config=Config.model_validate(config).model_copy(deep=True);self.clock=clock
        self.path=Path(self.config.database)
        if not self.path.is_absolute():self.path=ROOT/self.path
        self.path=self.path.resolve()
        if not local_storage_path(self.path):raise ValueError('Spool must be local')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path,timeout=1)) as db:
            db.execute('PRAGMA journal_mode=WAL');db.executescript(SCHEMA)
        with self.connect() as db:
            policy=hashlib.sha256(self.config.model_dump_json(exclude={'database','alerts_database','dataset_manifest','cloud_enabled'}).encode()).hexdigest()
            old=self._meta(db,'policy_sha256')
            if self.config.cloud_enabled:
                if old is not None and old!=policy:raise DedupeConflict('Spool policy changed; use a new spool or reviewed migration')
                self._set(db,'policy_sha256',policy)
            if self._meta(db,'device_id') is None:self._set(db,'device_id',str(uuid.uuid4()))
            self.device_id=self._meta(db,'device_id')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=.25,isolation_level=None)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA busy_timeout=250')
        try:db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @staticmethod
    def _meta(db,key,default=None):
        row=db.execute('SELECT value FROM qci4_meta WHERE key=?',(key,)).fetchone();return row[0] if row else default
    @staticmethod
    def _set(db,key,value):
        if key=='alert_cursor':
            prior=db.execute('SELECT value FROM qci4_meta WHERE key=?',(key,)).fetchone()
            value=max(int(value),int(prior[0]) if prior else 0)
        db.execute('INSERT OR REPLACE INTO qci4_meta VALUES(?,?)',(key,str(value)))
    def get_meta(self,key,default=None):
        with self.connect() as db:return self._meta(db,key,default)
    def set_meta(self,key,value):
        with self.connect() as db:self._set(db,key,value)
    def _counter(self,db,key):self._set(db,key,int(self._meta(db,key,'0'))+1)

    def _log(self,db,code,**fields):
        # Callers supply categories, counts and UUIDs only, never secrets or raw payloads.
        db.execute('INSERT INTO qci4_log(time,code,fields) VALUES(?,?,?)',
            (utc(self.clock()).isoformat(),code,json.dumps(fields,allow_nan=False,separators=(',',':'))))
        db.execute('DELETE FROM qci4_log WHERE id NOT IN (SELECT id FROM qci4_log ORDER BY id DESC LIMIT ?)',(self.config.audit_capacity,))
    def log(self,code,**fields):
        with self.connect() as db:self._log(db,code,**fields)

    def _cleanup(self,db):
        now=self.clock();c=self.config
        # Only routine samples can expire before delivery. Event summaries remain explicit.
        expired=db.execute("SELECT seq FROM qci4_spool WHERE kind='telemetry' AND state!='IN_FLIGHT' AND created<?",(now-c.routine_ttl_seconds,)).fetchall()
        for row in expired:
            db.execute('DELETE FROM qci4_spool WHERE seq=?',(row[0],));self._counter(db,'routine_expired_total')
        receipts=db.execute('SELECT created FROM qci4_receipts WHERE created<?',(now-c.receipt_ttl_seconds,)).fetchall()
        excess=db.execute('SELECT created FROM qci4_receipts ORDER BY created DESC LIMIT -1 OFFSET ?',(c.receipt_capacity,)).fetchall()
        if receipts or excess:
            watermark=max(float(self._meta(db,'replay_before','0')),max(r[0] for r in receipts+excess))
            self._set(db,'replay_before',watermark)
            db.execute('DELETE FROM qci4_receipts WHERE created<=?',(watermark,))
        db.execute("DELETE FROM qci4_spool WHERE state='DELIVERED'")

    def enqueue(self,key,payload,cursor=None,_connection=None):
        """Only typed allowlisted metadata; cursor and enqueue commit together."""
        p=ADAPTER.validate_python(payload);c=self.config
        allowed=c.cloud_enabled and (c.allow_telemetry_sync if p.kind=='telemetry' else c.allow_event_sync)
        if not allowed:return None
        encoded=json.dumps(p.model_dump(mode='json'),sort_keys=True,separators=(',',':'),allow_nan=False)
        size=len(encoded.encode());digest=hashlib.sha256(encoded.encode()).hexdigest()
        if size>c.item_max_bytes:raise ValueError('Sync item exceeds configured payload bound')
        if len(key)>128 or not key or any(ch not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-' for ch in key):raise ValueError('Invalid dedupe key')
        # Two edge devices may both observe audit row 1; receiver keys must not collide.
        key=self.device_id+':'+hashlib.sha256(key.encode()).hexdigest()
        identifier=str(uuid.uuid5(uuid.UUID(self.device_id),key));created=p.observed_at.timestamp()
        if p.observed_at.tzinfo is None:raise ValueError('Timezone-aware payload timestamp required')
        overflow=None
        with (self.connect() if _connection is None else nullcontext(_connection)) as db:
            self._cleanup(db)
            prior=db.execute('SELECT digest,id FROM qci4_spool WHERE dedupe=? UNION ALL SELECT digest,id FROM qci4_receipts WHERE dedupe=?',(key,key)).fetchone()
            if prior:
                if prior[0]!=digest:raise DedupeConflict('Dedupe key reused with different immutable payload')
                if cursor is not None:self._set(db,'alert_cursor',cursor)
                return prior[1]
            if created<=float(self._meta(db,'replay_before','0')):raise DedupeConflict('Payload predates retained replay watermark')
            total,used=db.execute('SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM qci4_spool').fetchone()
            routine=db.execute("SELECT COUNT(*) FROM qci4_spool WHERE kind='telemetry'").fetchone()[0]
            if p.kind=='telemetry' and routine>=c.routine_max_items:
                self._counter(db,'routine_skipped_total');return None
            # Make space for event summaries by discarding unsent routine samples only.
            while p.kind=='event_summary' and (total>=c.spool_max_items or used+size>c.spool_max_payload_bytes):
                disposable=db.execute("SELECT seq,bytes FROM qci4_spool WHERE kind='telemetry' AND attempts=0 AND state='PENDING' ORDER BY seq LIMIT 1").fetchone()
                if not disposable:break
                db.execute('DELETE FROM qci4_spool WHERE seq=?',(disposable[0],));total-=1;used-=disposable[1];self._counter(db,'routine_skipped_total')
            if total>=c.spool_max_items or used+size>c.spool_max_payload_bytes or shutil.disk_usage(self.path.parent).free<c.minimum_disk_free_bytes:
                self._counter(db,'overflow_total');self._log(db,'SPOOL_OVERFLOW',payload_type=p.kind,queue_depth=total)
                overflow='Bounded spool full or disk reserve reached; local QCI-3 state preserved'
            else:
                activation=p.activation_key if p.kind=='event_summary' else None
                priority={'info':1,'warning':2,'critical':3}[p.severity] if p.kind=='event_summary' else 0
                db.execute('INSERT INTO qci4_spool(id,dedupe,created,kind,activation,priority,payload,bytes,digest,state,due) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (identifier,key,created,p.kind,activation,priority,encoded,size,digest,'PENDING',self.clock()))
                if cursor is not None:self._set(db,'alert_cursor',cursor)
                self._log(db,'SYNC_QUEUED',item_id=identifier,queue_depth=total+1)
        if overflow:raise OverflowError(overflow)
        return identifier

    def enqueue_batch(self,items):
        """Commit a bounded audit batch once; preserve accepted prefix on backpressure."""
        if len(items)>32:raise ValueError('Summary batch exceeds 32 rows')
        failure=None
        with self.connect() as db:
            for key,payload,cursor in items:
                try:
                    if payload is None:self._set(db,'alert_cursor',cursor)
                    else:self.enqueue(key,payload,cursor=cursor,_connection=db)
                except OverflowError as exc:failure=exc;break
        if failure:raise failure

    def claim(self):
        now=self.clock();c=self.config
        with self.connect() as db:
            self._cleanup(db)
            expired=db.execute("SELECT * FROM qci4_spool WHERE state='IN_FLIGHT' AND lease<=?",(now,)).fetchall()
            for row in expired:
                state='FAILED_RETRYABLE' if c.receiver_idempotent and row['attempts']<c.attempts else 'DELIVERY_UNKNOWN'
                db.execute('UPDATE qci4_spool SET state=?,due=?,last_error=? WHERE seq=?',(state,now,'expired_dispatch_lease',row['seq']))
            row=db.execute('''SELECT s.* FROM qci4_spool s WHERE s.state IN ('PENDING','FAILED_RETRYABLE') AND s.due<=?
                AND (s.activation IS NULL OR NOT EXISTS(SELECT 1 FROM qci4_spool before
                  WHERE before.activation=s.activation AND before.seq<s.seq AND before.state!='DELIVERED'))
                ORDER BY s.priority DESC,s.seq LIMIT 1''',(now,)).fetchone()
            if row is None:return None
            if row['attempts']>=c.attempts:
                db.execute("UPDATE qci4_spool SET state='DELIVERY_UNKNOWN',last_error='retry_budget_exhausted' WHERE seq=?",(row['seq'],));return None
            db.execute("UPDATE qci4_spool SET state='IN_FLIGHT',attempts=attempts+1,last_attempt=?,lease=? WHERE seq=?",
                (now,now+2*c.request_timeout_seconds+2,row['seq']))
            value=dict(row);value['attempts']+=1;return value

    def complete(self,row,state,error=None,http_status=None,next_attempt=0):
        state=SyncState(state)
        with self.connect() as db:
            db.execute('UPDATE qci4_spool SET state=?,due=?,lease=0,last_error=?,last_http_status=? WHERE id=?',
                (state.value,next_attempt,error,http_status,row['id']))
            if state==SyncState.DELIVERED:
                db.execute('INSERT OR REPLACE INTO qci4_receipts VALUES(?,?,?,?)',(row['dedupe'],row['digest'],row['id'],row['created']))
                self._counter(db,'delivered_total');self._set(db,'last_successful_sync',self.clock())
            code='SYNC_DELIVERED' if state==SyncState.DELIVERED else 'SYNC_RETRY' if state==SyncState.FAILED_RETRYABLE else 'SYNC_FAILED'
            self._log(db,code,item_id=row['id'],attempt=row['attempts'],error_category=error,http_status=http_status)
            self._cleanup(db)

    def stats(self):
        with self.connect() as db:
            self._cleanup(db)
            counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM qci4_spool GROUP BY state')}
            total,used=db.execute('SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM qci4_spool').fetchone()
            oldest=db.execute("SELECT MIN(created) FROM qci4_spool WHERE state IN ('PENDING','FAILED_RETRYABLE','IN_FLIGHT')").fetchone()[0]
            receipt_count=db.execute('SELECT COUNT(*) FROM qci4_receipts').fetchone()[0]
            counters={k:int(self._meta(db,k,'0')) for k in ('delivered_total','overflow_total','routine_expired_total','routine_skipped_total')}
        size=0
        for path in (self.path,Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')):
            try:size+=path.stat().st_size
            except FileNotFoundError:pass  # WAL/SHM can disappear during a concurrent checkpoint.
        return SpoolStats(pending=counts.get('PENDING',0)+counts.get('FAILED_RETRYABLE',0),in_flight=counts.get('IN_FLIGHT',0),
            failed_permanent=counts.get('FAILED_PERMANENT',0),unknown=counts.get('DELIVERY_UNKNOWN',0),owned_rows=total,
            payload_bytes=used,database_bytes=size,oldest_pending_age_seconds=max(0,self.clock()-oldest) if oldest is not None else None,
            receipt_rows=receipt_count,**counters)

    def item(self,identifier):
        with self.connect() as db:
            row=db.execute('SELECT * FROM qci4_spool WHERE id=?',(identifier,)).fetchone()
            return dict(row) if row else None

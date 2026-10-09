"""Transactionally durable states/outbox, without classifier or network work."""
from __future__ import annotations
from contextlib import contextmanager,closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3
import time
import uuid
from Backend.incidents.repository import local_storage_path,ROOT
from SED_2_Alert_Escalation.scripts.models import Severity,EventState,HazardRule
from SED_2_Alert_Escalation.scripts.severity_engine import SeverityEngine
from .contracts import Config,Event,Status,Resolve,Delivery,WebhookPayload

class CapacityError(RuntimeError):pass
class ConflictError(ValueError):pass

VALID_TRANSITIONS={EventState.INACTIVE:{EventState.INFO,EventState.WARNING,EventState.CRITICAL},
    EventState.INFO:{EventState.WARNING,EventState.CRITICAL,EventState.RESOLVED},
    EventState.WARNING:{EventState.CRITICAL,EventState.RESOLVED},
    EventState.CRITICAL:{EventState.RESOLVED},EventState.RESOLVED:set()}

def transition(before,after):
    before,after=EventState(before),EventState(after)
    if after not in VALID_TRANSITIONS[before]:raise ConflictError(f'Invalid transition: {before.value} -> {after.value}')
    return after

SCHEMA='''
CREATE TABLE IF NOT EXISTS qci3_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qci3_events(
 source TEXT NOT NULL,event TEXT NOT NULL,status TEXT NOT NULL,digest TEXT NOT NULL,
 resolved INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL,PRIMARY KEY(source,event));
CREATE INDEX IF NOT EXISTS qci3_events_retention ON qci3_events(resolved,updated);
CREATE TABLE IF NOT EXISTS qci3_audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,event TEXT NOT NULL,
 time TEXT NOT NULL,before_state TEXT NOT NULL,after_state TEXT NOT NULL,detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS qci3_outbox(
 id TEXT PRIMARY KEY,source TEXT NOT NULL,event TEXT NOT NULL,payload TEXT NOT NULL,
 state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,due REAL NOT NULL,
 lease REAL NOT NULL DEFAULT 0,last_error TEXT,last_http_status INTEGER);
CREATE INDEX IF NOT EXISTS qci3_outbox_due ON qci3_outbox(state,due);
'''

class AlarmEngine:
    def __init__(self,config:Config|dict,clock=time.time):
        self.config=Config.model_validate(config).model_copy(deep=True);self.clock=clock
        self.path=Path(self.config.database)
        if not self.path.is_absolute():self.path=ROOT/self.path
        self.path=self.path.resolve()
        if not local_storage_path(self.path):raise ValueError('Database must be local')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.policy=SeverityEngine({k:HazardRule(k,r.initial,r.warning_after_seconds,r.critical_after_seconds,
            geofence_overrides=r.source_overrides,category='quality') for k,r in self.config.rules.items()})
        with closing(sqlite3.connect(self.path,timeout=1)) as db:
            db.execute('PRAGMA journal_mode=WAL');db.executescript(SCHEMA)
        with self.connect() as db:
            # Moving an identical database is not a severity/transport policy change.
            identity=hashlib.sha256(self.config.model_dump_json(exclude={'database'}).encode()).hexdigest()
            row=db.execute("SELECT value FROM qci3_meta WHERE key='config_sha256'").fetchone()
            if row and row[0]!=identity:raise ConflictError('Policy/config changed: use a new database or reviewed migration')
            db.execute("INSERT OR IGNORE INTO qci3_meta VALUES('config_sha256',?)",(identity,))

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=1,isolation_level=None)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA busy_timeout=1000')
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def _cleanup(self,db):
        now=self.clock()
        # A retention watermark permanently rejects replay of forgotten event IDs/timestamps.
        rows=db.execute('''SELECT source,event,updated,status FROM qci3_events WHERE resolved=1 AND updated<?
            AND NOT EXISTS(SELECT 1 FROM qci3_outbox o WHERE o.source=qci3_events.source
             AND o.event=qci3_events.event AND o.state IN ('PENDING','IN_FLIGHT'))''',
            (now-self.config.resolved_ttl_seconds,)).fetchall()
        if rows:
            prior=db.execute("SELECT value FROM qci3_meta WHERE key='replay_before'").fetchone()
            cutoff=max(float(prior[0]) if prior else 0,max(Status.model_validate_json(r['status']).last_seen.timestamp() for r in rows))
            db.execute("INSERT OR REPLACE INTO qci3_meta VALUES('replay_before',?)",(str(cutoff),))
            for r in rows:
                db.execute('DELETE FROM qci3_outbox WHERE source=? AND event=?',(r['source'],r['event']))
                db.execute('DELETE FROM qci3_events WHERE source=? AND event=?',(r['source'],r['event']))
        db.execute('DELETE FROM qci3_audit WHERE id NOT IN (SELECT id FROM qci3_audit ORDER BY id DESC LIMIT ?)',
            (self.config.audit_capacity,))

    def _audit(self,db,status,before,detail):
        detail=json.dumps({'reason':detail,'class_name':status.class_name,'confidence':status.confidence,
            'sample_id':status.sample_id,'model_version':status.model_version,'policy_version':status.policy_version,
            'actions':status.actions,'delivery':status.delivery.value},separators=(',',':'))
        db.execute('INSERT INTO qci3_audit(source,event,time,before_state,after_state,detail) VALUES(?,?,?,?,?,?)',
            (status.source_id,status.event_id,status.last_transition.isoformat(),before.value,status.state.value,detail))
        db.execute('DELETE FROM qci3_audit WHERE id NOT IN (SELECT id FROM qci3_audit ORDER BY id DESC LIMIT ?)',
            (self.config.audit_capacity,))

    def process(self,event:Event|dict)->Status:
        event=Event.model_validate(event).model_copy(deep=True)
        p=event.prediction;c=self.config
        if p.model_version!=c.expected_model_version:raise ConflictError('Unrecognized QCI-2 model version')
        digest=hashlib.sha256(event.model_dump_json().encode()).hexdigest()
        with self.connect() as db:
            self._cleanup(db)
            row=db.execute('SELECT * FROM qci3_events WHERE source=? AND event=?',(event.source_id,event.event_id)).fetchone()
            old=Status.model_validate_json(row['status']) if row else None
            if old and event.sequence==old.sequence:
                if row['digest']!=digest:raise ConflictError('Sequence reused with different data')
                return old.model_copy(update={'duplicate':True,'actions':[],
                    'decision_latency_ms':0,'transition_latency_ms':0,'local_action_latency_ms':0})
            if old and old.state==EventState.RESOLVED:raise ConflictError('Resolved identity cannot recur; use a new event_id')
            if old and (event.sequence<old.sequence or event.observed_at<old.last_seen):raise ConflictError('Out-of-order observation')
            if old and p.sample_id!=old.sample_id:
                raise ConflictError('Sample identity changed')
            before=old.state if old else EventState.INACTIVE
            if not old:
                watermark=db.execute("SELECT value FROM qci3_meta WHERE key='replay_before'").fetchone()
                if watermark and event.observed_at.timestamp()<=float(watermark[0]):raise ConflictError('Observation predates retained replay watermark')
                total=db.execute('SELECT COUNT(*) FROM qci3_events').fetchone()[0]
                active=db.execute('SELECT COUNT(*) FROM qci3_events WHERE resolved=0').fetchone()[0]
                if total>=c.record_capacity or active>=c.active_capacity:raise CapacityError('Alarm capacity reached; active events preserved')
            first=old.first_seen if old else event.observed_at
            decision_start=time.perf_counter()
            decision=self.policy.decide(p.predicted_class_name,(event.observed_at-first).total_seconds(),event.source_id)
            decision_ms=(time.perf_counter()-decision_start)*1000
            transition_start=time.perf_counter()
            severity=decision.severity
            if old and old.severity.rank>severity.rank:severity=old.severity
            state=EventState(severity.value)
            changed=before!=state
            if changed:transition(before,state)
            transition_ms=(time.perf_counter()-transition_start)*1000
            action_start=time.perf_counter()
            actions=(['log','dashboard_info'] if severity==Severity.INFO else ['log','dashboard_warning']
                if severity==Severity.WARNING else ['log','dashboard_critical','iot_siren']) if changed else []
            status=Status(source_id=event.source_id,event_id=event.event_id,sample_id=p.sample_id,state=state,severity=severity,
                first_seen=first,last_seen=event.observed_at,last_transition=event.observed_at if changed else old.last_transition,
                sequence=event.sequence,model_version=p.model_version,policy_version=c.policy_version,
                class_name=p.predicted_class_name,confidence=p.confidence,reason=decision.reason,actions=actions,
                delivery=old.delivery if old else Delivery.DISABLED,delivery_id=old.delivery_id if old else None,
                delivery_attempts=old.delivery_attempts if old else 0,last_http_status=old.last_http_status if old else None,
                last_delivery_error=old.last_delivery_error if old else None,
                decision_latency_ms=decision_ms,transition_latency_ms=transition_ms)
            if changed and severity==Severity.CRITICAL and c.webhook.enabled:
                pending=db.execute("SELECT COUNT(*) FROM qci3_outbox WHERE state IN ('PENDING','IN_FLIGHT')").fetchone()[0]
                status.delivery_id=str(uuid.uuid4())
                if pending>=c.outbox_capacity:
                    status.delivery=Delivery.FAILED;status.reason+=' Delivery queue full; critical state preserved.'
                    status.last_delivery_error='queue_capacity_reached'
                else:
                    status.delivery=Delivery.PENDING
                    payload=WebhookPayload(delivery_id=status.delivery_id,source_id=status.source_id,event_id=status.event_id,
                        sample_id=p.sample_id,model_version=p.model_version,policy_version=c.policy_version,
                        observed_at=event.observed_at,class_name=p.predicted_class_name,confidence=p.confidence).model_dump(mode='json')
                    db.execute('INSERT INTO qci3_outbox(id,source,event,payload,state,due) VALUES(?,?,?,?,?,?)',
                        (status.delivery_id,status.source_id,status.event_id,json.dumps(payload),'PENDING',self.clock()))
            db.execute('INSERT OR REPLACE INTO qci3_events VALUES(?,?,?,?,0,?)',
                (status.source_id,status.event_id,status.model_dump_json(),digest,self.clock()))
            if changed:self._audit(db,status,before,status.reason)
            status.local_action_latency_ms=(time.perf_counter()-action_start)*1000
            db.execute('UPDATE qci3_events SET status=? WHERE source=? AND event=?',
                (status.model_dump_json(),status.source_id,status.event_id))
            return status

    def resolve(self,request:Resolve|dict)->Status:
        request=Resolve.model_validate(request)
        with self.connect() as db:
            row=db.execute('SELECT * FROM qci3_events WHERE source=? AND event=?',(request.source_id,request.event_id)).fetchone()
            if not row:raise ConflictError('Unknown event')
            status=Status.model_validate_json(row['status'])
            if status.state==EventState.RESOLVED:return status.model_copy(update={'duplicate':True,'actions':[]})
            if request.observed_at<status.last_seen:raise ConflictError('Resolution predates last observation')
            before=status.state;transition(before,EventState.RESOLVED)
            status.state=EventState.RESOLVED;status.last_seen=request.observed_at;status.last_transition=request.observed_at
            status.actions=['log','dashboard_resolved'];status.reason='Explicitly resolved; recurrence requires new event_id.'
            # An unsent activation must not actuate a siren after local resolution.
            db.execute("UPDATE qci3_outbox SET state='FAILED',last_error='resolved_before_dispatch' WHERE source=? AND event=? AND state='PENDING'",
                (status.source_id,status.event_id))
            if status.delivery==Delivery.PENDING:
                pending=db.execute('SELECT state FROM qci3_outbox WHERE id=?',(status.delivery_id,)).fetchone()
                if pending and pending[0]=='FAILED':status.delivery=Delivery.FAILED
            db.execute('UPDATE qci3_events SET status=?,resolved=1,updated=? WHERE source=? AND event=?',
                (status.model_dump_json(),self.clock(),status.source_id,status.event_id))
            self._audit(db,status,before,status.reason);return status

    def get(self,source,event):
        with self.connect() as db:
            row=db.execute('SELECT status FROM qci3_events WHERE source=? AND event=?',(source,event)).fetchone()
            if not row:raise KeyError('Unknown event')
            return Status.model_validate_json(row[0])

    def snapshot(self,limit=100):
        with self.connect() as db:
            self._cleanup(db)
            counts={r[0]:r[1] for r in db.execute('SELECT resolved,COUNT(*) FROM qci3_events GROUP BY resolved')}
            rows=db.execute('SELECT status FROM qci3_events ORDER BY updated DESC LIMIT ?',(min(max(int(limit),1),100),)).fetchall()
            deliveries={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM qci3_outbox GROUP BY state')}
            return {'policy_version':self.config.policy_version,'model_version':self.config.expected_model_version,
                'active':counts.get(0,0),'resolved':counts.get(1,0),'webhook_enabled':self.config.webhook.enabled,
                'delivery_counts':deliveries,
                'events':[Status.model_validate_json(r[0]).model_dump(mode='json') for r in rows]}

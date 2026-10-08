from __future__ import annotations
import json
import os
import re
import sqlite3
import time
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ID_PATTERN = re.compile(r'INC-\d{4}-\d{3,12}\Z')

def local_storage_path(value):
    text=str(value)
    if text.startswith(('\\\\','//')) or '://' in text:return False
    path=Path(value)
    if not path.is_absolute():path=ROOT/path
    if sys.platform=='win32':
        import ctypes
        function=ctypes.windll.kernel32.GetDriveTypeW
        function.argtypes=[ctypes.c_wchar_p];function.restype=ctypes.c_uint
        return function(path.anchor) in (2,3,6)  # removable, fixed, RAM; never SMB/mapped network.
    return True

def utc(value=None):
    return datetime.fromtimestamp(time.time() if value is None else float(value),timezone.utc).isoformat(timespec='microseconds')

def validate_id(value):
    if not ID_PATTERN.fullmatch(value):raise ValueError('Expected incident ID INC-YYYY-NNN, with at least three sequence digits')
    return value

def event_key(event):
    metadata=event.get('metadata') or {}
    # SED-2 counters restart. The CME UUID and episode onset prevent collisions
    # across restarts, cameras, and resolved/recurrent SED-2 episodes.
    return json.dumps([event['camera_id'],metadata.get('violation_id'),event['event_id'],float(event['first_seen'])],separators=(',',':'))

SCHEMA = '''
CREATE TABLE IF NOT EXISTS incident_sequence(year INTEGER PRIMARY KEY, next_value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS incidents(
 id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL UNIQUE,
 source_event_key TEXT NOT NULL UNIQUE, event_id TEXT NOT NULL, violation_id TEXT,
 timestamp TEXT NOT NULL, camera_id TEXT NOT NULL, camera_location TEXT NOT NULL,
 class_id INTEGER NOT NULL, class_name TEXT NOT NULL, confidence REAL NOT NULL,
 severity TEXT NOT NULL CHECK(severity IN ('info','warning','critical')),
 bbox_x1 REAL NOT NULL,bbox_y1 REAL NOT NULL,bbox_x2 REAL NOT NULL,bbox_y2 REAL NOT NULL,
 coordinate_format TEXT NOT NULL DEFAULT 'xyxy source-frame pixels',
 image_width INTEGER NOT NULL,image_height INTEGER NOT NULL,
 track_id INTEGER,geofence_id TEXT,confirmation_frames INTEGER,
 first_seen TEXT,confirmed_at TEXT,last_seen TEXT,resolved_at TEXT,
 snapshot_path TEXT,snapshot_status TEXT NOT NULL DEFAULT 'pending',snapshot_error TEXT,
 snapshot_sha256 TEXT,crop_rect TEXT,snapshot_width INTEGER,snapshot_height INTEGER,
 evidence_frame_id INTEGER,evidence_timestamp TEXT,snapshot_lease_until REAL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'OPEN',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 engine_version TEXT,detector_version TEXT,alert_policy_version TEXT,
 is_sample INTEGER NOT NULL DEFAULT 0,operator_name TEXT,operator_notes TEXT,corrective_action TEXT
);
CREATE INDEX IF NOT EXISTS incidents_time ON incidents(timestamp);
CREATE INDEX IF NOT EXISTS incidents_camera ON incidents(camera_id);
CREATE TABLE IF NOT EXISTS incident_transitions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,incident_id TEXT NOT NULL REFERENCES incidents(incident_id),
 timestamp TEXT NOT NULL,severity TEXT NOT NULL,status TEXT NOT NULL
);
'''

class IncidentRepository:
    def __init__(self,database=None,snapshots=None,initialize=True):
        def resolved(value):
            if not local_storage_path(value):raise ValueError('Incident storage must use a local filesystem path')
            p=Path(value);p=(ROOT/p if not p.is_absolute() else p).resolve()
            if not local_storage_path(p):raise ValueError('Resolved incident storage is not local')
            return p
        self.database=resolved(database or os.getenv('INCIDENT_DATABASE','Backend/data/events.db'))
        self.snapshots=resolved(snapshots or os.getenv('INCIDENT_SNAPSHOTS','data/snapshots'))
        if not all(local_storage_path(p) for p in (self.database,self.snapshots)):
            raise ValueError('Incident storage must use local filesystem paths, not UNC/network drives or URLs')
        if initialize:
            self.database.parent.mkdir(parents=True,exist_ok=True)
            with self.connect() as db:
                version=db.execute('PRAGMA user_version').fetchone()[0]
                if version>1:raise RuntimeError('Incident database version is newer than this service; no migration attempted')
                db.execute('PRAGMA journal_mode=WAL')
                # Existing unrelated tables/data are preserved. An incompatible
                # incidents table is rejected, never dropped or silently replaced.
                existing={r[1] for r in db.execute('PRAGMA table_info(incidents)')}
                if existing and not {'source_event_key','snapshot_status','violation_id'}<=existing:
                    raise RuntimeError('Existing incidents schema requires a reviewed migration; original data preserved')
                db.executescript(SCHEMA);db.execute('PRAGMA user_version=1')

    @contextmanager
    def connect(self,readonly=False):
        if readonly:
            if not self.database.is_file():raise FileNotFoundError('Local incident database is not initialized')
            db=sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True,timeout=1)
        else:db=sqlite3.connect(self.database,timeout=1)
        db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=1000')
        try:
            yield db
            if not readonly:db.commit()
        except Exception:
            if not readonly:db.rollback()
            raise
        finally:db.close()

    def get(self,incident_id):
        validate_id(incident_id)
        with self.connect(readonly=True) as db:
            row=db.execute('SELECT * FROM incidents WHERE incident_id=?',(incident_id,)).fetchone()
            if row is None:raise KeyError(incident_id)
            return dict(row)

    def list(self,limit=100):
        with self.connect(readonly=True) as db:
            return [dict(r) for r in db.execute('SELECT * FROM incidents ORDER BY id DESC LIMIT ?',(min(200,max(1,int(limit))),))]

    def reserve(self,values):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM incidents WHERE source_event_key=?',(values['source_event_key'],)).fetchone()
            if row:return dict(row),False
            year=datetime.fromisoformat(values['timestamp']).year
            db.execute('INSERT OR IGNORE INTO incident_sequence VALUES (?,1)',(year,))
            sequence=db.execute('SELECT next_value FROM incident_sequence WHERE year=?',(year,)).fetchone()[0]
            db.execute('UPDATE incident_sequence SET next_value=next_value+1 WHERE year=?',(year,))
            values={**values,'incident_id':f'INC-{year}-{sequence:03d}', 'created_at':utc(),'updated_at':utc(),
                    'snapshot_lease_until':time.time()+30}
            columns=list(values)
            db.execute('INSERT INTO incidents ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                       [values[k] for k in columns])
            db.execute('INSERT INTO incident_transitions(incident_id,timestamp,severity,status) VALUES(?,?,?,?)',
                       (values['incident_id'],values['timestamp'],values['severity'],'OPEN'))
            row=db.execute('SELECT * FROM incidents WHERE incident_id=?',(values['incident_id'],)).fetchone()
            return dict(row),True

    def claim_snapshot(self,incident_id):
        with self.connect() as db:
            return db.execute("UPDATE incidents SET snapshot_status='pending',snapshot_lease_until=? WHERE incident_id=? AND snapshot_status IN ('pending','failed') AND snapshot_lease_until<?",
                              (time.time()+30,incident_id,time.time())).rowcount==1

    def finish_snapshot(self,incident_id,values):
        allowed={'snapshot_path','snapshot_status','snapshot_error','snapshot_sha256','crop_rect','snapshot_width',
                 'snapshot_height','evidence_frame_id','evidence_timestamp'}
        if not set(values)<=allowed:raise ValueError('Invalid evidence metadata field')
        with self.connect() as db:
            db.execute('UPDATE incidents SET '+','.join(k+'=?' for k in values)+',snapshot_lease_until=0,updated_at=? WHERE incident_id=?',
                       [*values.values(),utc(),validate_id(incident_id)])

    def lifecycle(self,event):
        key=event_key(event);severity=event['severity'];status='RESOLVED' if event['state']=='resolved' else 'OPEN'
        if severity not in ('info','warning','critical'):return
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM incidents WHERE source_event_key=?',(key,)).fetchone()
            if row is None:return
            resolved=utc((event.get('metadata') or {}).get('resolution_observed_at',time.time())) if status=='RESOLVED' else row['resolved_at']
            if row['severity']!=severity or row['status']!=status:
                db.execute('INSERT INTO incident_transitions(incident_id,timestamp,severity,status) VALUES(?,?,?,?)',
                    (row['incident_id'],resolved if status=='RESOLVED' else utc(event['last_seen']),severity,status))
            db.execute('UPDATE incidents SET severity=?,status=?,last_seen=?,resolved_at=?,updated_at=? WHERE source_event_key=?',
                       (severity,status,utc(event['last_seen']),resolved,utc(),key))

    def transitions(self,incident_id):
        with self.connect(readonly=True) as db:
            return [dict(r) for r in db.execute('SELECT timestamp,severity,status FROM incident_transitions WHERE incident_id=? ORDER BY id',(validate_id(incident_id),))]

    def snapshot_file(self,row):
        if not row.get('snapshot_path'):return None
        path=(self.snapshots/row['snapshot_path']).resolve()
        if not path.is_relative_to(self.snapshots):raise ValueError('Evidence path is outside the snapshot directory')
        return path

"""Read existing hazard/QCI-3 records; never create a parallel event database."""
import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from Backend.incidents.repository import ROOT, local_storage_path, validate_id
from QCI_3_Severity_IoT.contracts import Status, parse_config
from .contracts import Config, Evidence, ReportData, Transition

def local_path(value):
    if not local_storage_path(value) or '..' in Path(value).parts:
        raise ValueError('Expected a local path without parent traversal')
    path = (ROOT / value).resolve()
    if not local_storage_path(path): raise ValueError('Resolved path is not local')
    return path

def quality_id(source, event):
    raw = json.dumps([source, event], separators=(',', ':')).encode()
    return 'QCI3-' + base64.urlsafe_b64encode(raw).decode().rstrip('=')

def identity(value):
    if not value.startswith('QCI3-'): validate_id(value); return None
    if len(value)>512 or not re.fullmatch(r'QCI3-[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid quality event report ID')
    try:
        token=value[5:]; pair=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        if not isinstance(pair, list) or len(pair)!=2: raise ValueError()
        if any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', v) for v in pair): raise ValueError()
        if quality_id(*pair)!=value: raise ValueError()
        return pair
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('Invalid quality event report ID') from exc

def configuration():
    path=os.getenv('QCI5_CONFIG')
    if not path: return Config()
    p=local_path(path)
    if p.stat().st_size>65536: raise ValueError('Report configuration exceeds 64 KiB')
    return Config.model_validate_json(p.read_text(encoding='utf-8'))

class Adapter:
    def __init__(self, legacy=None, config=None, telemetry=None):
        self.config=config or configuration(); self.legacy=legacy; self.telemetry=telemetry
        value=self.config.quality_database
        if not value and os.getenv('QCI3_CONFIG'):
            p=local_path(os.environ['QCI3_CONFIG'])
            if p.stat().st_size>65536: raise ValueError('Alarm configuration exceeds bound')
            value=parse_config(p.read_text(encoding='utf-8')).database
        self.database=local_path(value or 'Backend/data/events.db')

    def connect(self):
        if not self.database.is_file(): raise FileNotFoundError('Local event storage unavailable')
        connection=sqlite3.connect(self.database.as_uri()+'?mode=ro', uri=True, timeout=1)
        connection.row_factory=sqlite3.Row
        return connection

    def list_quality(self, limit=100):
        if not 1<=limit<=200: raise ValueError('List limit out of range')
        if not self.database.is_file(): return []
        with closing(self.connect()) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='qci3_events'").fetchone(): return []
            rows=db.execute('SELECT status FROM qci3_events ORDER BY updated DESC LIMIT ?', (limit,)).fetchall()
        # No classification/heatmap objects are retained or loaded here.
        result=[]
        for row in rows:
            s=Status.model_validate_json(row['status'])
            result.append(dict(incident_id=quality_id(s.source_id,s.event_id),timestamp=s.first_seen.isoformat(),
                camera_location=s.source_id,class_name=s.class_name,severity=s.severity.value,
                confidence=s.confidence,status=s.state.value,snapshot_status='Not recorded in QCI-3',
                # Delivery acknowledgements can change without last_seen advancing.
                # The complete stored status digest invalidates that UI download too.
                updated_at=hashlib.sha256(row['status'].encode()).hexdigest(),is_sample=None,origin='QCI-3'))
        return result

    def load(self, incident_id):
        pair=identity(incident_id)
        if pair:
            with closing(self.connect()) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE name='qci3_events'").fetchone(): raise KeyError(incident_id)
                # One SQLite read snapshot; closed before evidence decoding or PDF rendering.
                db.execute('BEGIN')
                row=db.execute('SELECT status,digest FROM qci3_events WHERE source=? AND event=?',pair).fetchone()
                if row is None: raise KeyError(incident_id)
                s=Status.model_validate_json(row['status'])
                if [s.source_id,s.event_id]!=pair:raise ValueError('Stored event identity mismatch')
                records=db.execute('SELECT time,after_state,detail FROM qci3_audit WHERE source=? AND event=? ORDER BY id LIMIT 201',pair).fetchall()
            warnings=[]
            if len(records)>200: warnings.append('TRANSITION_HISTORY_LIMIT: first 200 retained transitions shown')
            data=ReportData(incident_id=incident_id,event_id=s.event_id,timestamp=s.first_seen,
                source_id=s.source_id,sample_id=s.sample_id,defect_class=s.class_name,
                severity=s.severity.value,state=s.state.value,confidence=s.confidence,
                model_version=s.model_version,policy_version=s.policy_version,delivery=s.delivery.value,
                delivery_attempts=s.delivery_attempts,transitions=[Transition(timestamp=r['time'],state=r['after_state'],
                    detail=json.loads(r['detail']).get('reason')) for r in records[:200]],warnings=warnings)
            self.attach_evidence(data,row['digest'])
        else:
            if self.legacy is None: raise FileNotFoundError('Legacy incident repository unavailable')
            r=self.legacy.get(incident_id)
            data=ReportData(incident_id=r['incident_id'],event_id=r['event_id'],timestamp=r['timestamp'],
                defect_class=r['class_name'],severity=r['severity'],state=r['status'],source_id=r['camera_id'],
                location=r['camera_location'],confidence=r['confidence'],model_version=r['detector_version'],
                policy_version=r['alert_policy_version'],bbox=tuple(r['bbox_'+axis] for axis in ('x1','y1','x2','y2')),
                track_id=r['track_id'],is_sample=bool(r['is_sample']),operator_name=r['operator_name'],
                operator_notes=r['operator_notes'],corrective_action=r['corrective_action'],
                transitions=[Transition(timestamp=h['timestamp'],state=h['severity'].upper()+' / '+h['status']) for h in self.legacy.transitions(incident_id)[:200]])
            try:
                path=self.legacy.snapshot_file(r)
                if path: data.evidence=[Evidence(role='Evidence image',path=str(path),sha256=r['snapshot_sha256'],
                    context='Native unannotated crop; recorded evidence timestamp: '+str(r['evidence_timestamp'] or 'Unavailable'))]
            except ValueError: data.warnings.append('EVIDENCE_INVALID: rejected snapshot path')
        if self.config.include_telemetry and self.telemetry:
            try: data.telemetry=self.telemetry()
            except Exception: data.warnings.append('TELEMETRY_UNAVAILABLE')
        return data

    def attach_evidence(self,data,digest):
        """Optional trusted local provenance manifest, bound to the exact stored event digest."""
        if not self.config.evidence_index: return
        try:
            path=local_path(self.config.evidence_index)
            if path.stat().st_size>1024*1024: raise ValueError('Evidence index exceeds 1 MiB')
            index=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(index,dict) or len(index)>100: raise ValueError('Evidence index exceeds 100 entries')
            entry=index.get(data.incident_id)
            if entry is None: return
            if entry['event_digest']!=digest: raise ValueError('Stale evidence binding')
            if not isinstance(entry['evidence'],list) or len(entry['evidence'])>2:raise ValueError('Evidence list exceeds budget')
            data.evidence=[Evidence.model_validate(e) for e in entry['evidence']]
            data.is_sample=entry.get('is_sample') is True
        except (OSError,ValueError,KeyError,TypeError): data.warnings.append('EVIDENCE_INVALID: unavailable or stale provenance manifest')

    def allowed_roots(self):
        roots=[local_path(p) for p in self.config.evidence_roots]
        if self.legacy is not None: roots.append(self.legacy.snapshots.resolve())
        return roots

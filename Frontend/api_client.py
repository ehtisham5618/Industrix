"""Bounded-time API calls and presentation parsing; no model or telemetry process."""
from urllib.parse import urlparse
import requests


class APIClient:
    def __init__(self,base_url):
        self.base_url=base_url.rstrip('/')
        parsed=urlparse(self.base_url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Use an HTTP(S) backend URL without embedded credentials')
        self.session=requests.Session()

    def request(self,method,path,**kwargs):
        return self.binary(method,path,**kwargs).json()

    def binary(self,method,path,**kwargs):
        response=self.session.request(method,self.base_url+path,timeout=(2,30 if method=='POST' else 3),**kwargs)
        try:response.raise_for_status()
        except requests.HTTPError as exc:
            try:detail=response.json().get('detail')
            except (ValueError,AttributeError):detail=None
            raise requests.HTTPError(str(detail or f'Backend returned HTTP {response.status_code}'),response=response) from exc
        return response


def engine_label(engine):
    if not engine.get('active'):return 'Idle'
    return f"{engine.get('name','Unknown')} {engine.get('precision','Unknown')} ({str(engine.get('device','Unknown')).upper()})"


def cloud_label(privacy):
    if privacy.get('local_processing_verified') is True and privacy.get('cloud_dependency_percent')==0:
        return '0% · Privacy-First On-Premise'
    return 'External or unverified deployment'


def camera_label(status):
    value=(status or {}).get('status','stopped')
    return {'running':'LIVE','starting':'CONNECTING','reconnecting':'RECONNECTING'}.get(value,'OFFLINE')


def telemetry_values(payload):
    """Parse unavailable numbers without falsely reporting zero consumption."""
    import math
    telemetry=payload.get('telemetry') or {}
    def number(key):
        value=telemetry.get(key)
        return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None
    return dict(cpu_percent=number('cpu_system_percent'),rss_mib=number('process_rss_mb'),
                evaluated_fps=number('aggregate_evaluated_fps'))

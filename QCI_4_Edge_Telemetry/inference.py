"""In-process bounded observations; no model ownership, files, sockets or SQLite."""
from collections import deque
import statistics
import threading
import time
import weakref
from .contracts import InferenceHealth,utc

class InferenceTracker:
    def __init__(self,capacity=128,clock=time.time):
        self.lock=threading.RLock();self.clock=clock;self.recent=deque(maxlen=capacity)
        self.model_reference=None;self.bound=False;self.count=0;self.failures=0
        self.last_at=None;self.last_error=None

    def bind(self,classifier):
        with self.lock:self.model_reference=weakref.ref(classifier);self.bound=True

    def configure_window(self,capacity):
        if not 1<=capacity<=512:raise ValueError('Inference history capacity outside bounds')
        with self.lock:self.recent=deque(self.recent,maxlen=capacity)

    def observe(self,result):
        with self.lock:
            self.last_at=self.clock()
            if result.status=='SUCCESS':
                self.count+=1;self.last_error=None
                if result.classifier_latency_ms is not None:self.recent.append((float(result.classifier_latency_ms),result.combined_latency_ms))
            else:self.failures+=1;self.last_error=(result.error_type or 'PredictionFailed')[:64]

    def snapshot(self,stale_seconds=60):
        with self.lock:
            model=self.model_reference() if self.model_reference else None
            loaded=model is not None and model.model is not None
            model_error=model is not None and model.error is not None
            version=model.metadata.get('model_version') if model is not None else None
            state='UNKNOWN' if not self.bound else 'ERROR' if model_error else 'LOADED' if loaded else 'UNLOADED'
            status='UNKNOWN' if not self.bound else 'ERROR' if model_error or self.last_error else 'IDLE' if self.last_at is None else 'STALE' if self.clock()-self.last_at>stale_seconds or not loaded else 'HEALTHY'
            values=[r[0] for r in self.recent];combined=[r[1] for r in self.recent if r[1] is not None]
            return InferenceHealth(status=status,model_status=state,model_loaded=loaded if self.bound else None,
                model_version=version,inference_count=self.count,failures=self.failures,recent_samples=len(values),
                latency_ms=statistics.mean(values) if values else None,p95_latency_ms=sorted(values)[min(len(values)-1,int(.95*len(values)))] if values else None,
                combined_latency_ms=statistics.mean(combined) if combined else None,
                last_inference_at=utc(self.last_at) if self.last_at is not None else None,last_error=self.last_error)

_TRACKER=InferenceTracker()
def get_tracker():return _TRACKER

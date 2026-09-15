from __future__ import annotations

import json
import logging
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .models import ActionRecord, AlertEvent


class EventStore:
    def __init__(self, log_path: str | Path | None = None, history_limit: int | None = None):
        self._lock = threading.Lock()
        self.events: dict[str, AlertEvent] = {}
        if history_limit is not None and history_limit < 1:
            raise ValueError('history_limit must be positive')
        self.history_limit = history_limit
        self.history = [] if history_limit is None else deque(maxlen=history_limit)
        self.action_records = [] if history_limit is None else deque(maxlen=history_limit)
        self.archived_events = 0
        self.log_path = Path(log_path) if log_path else None
        self.transition_callback = None
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_event(self, event: AlertEvent) -> None:
        with self._lock:
            self.events[event.event_id] = event
            if self.history_limit is not None:
                while len(self.events) > self.history_limit:
                    resolved = next((key for key, item in self.events.items()
                                     if item.state.value == 'resolved'), None)
                    if resolved is None:
                        break  # Live safety incidents are never evicted.
                    archived = self.events.pop(resolved)
                    self.archived_events += 1
                    if self.log_path:
                        with self.log_path.open('a', encoding='utf-8') as fh:
                            fh.write(json.dumps({'type':'archived_event', **archived.to_dict()}, sort_keys=True)+'\n')

    def record_transition(self, event: AlertEvent, previous_state: str, reason: str) -> None:
        entry = {
            "timestamp": event.last_seen,
            "event_id": event.event_id,
            "camera_id": event.camera_id,
            "hazard_class": event.hazard_class,
            "transition": f"{previous_state}->{event.state.value}",
            "severity": event.severity.value,
            "geofence_id": event.geofence_id,
            "duration": event.duration,
            "reason": reason,
        }
        with self._lock:
            self.history.append(entry)
            if self.log_path:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, sort_keys=True) + "\n")

        # Optional incident lifecycle observer; PDF/snapshot generation never
        # runs in this hook. Audit failures must not terminate safety handling.
        if self.transition_callback is not None:
            try:self.transition_callback(event.to_dict())
            except Exception:
                logging.getLogger(__name__).exception('INCIDENT_LIFECYCLE_OBSERVER_FAILED')

    def record_action(self, record: ActionRecord) -> None:
        entry = {"type": "action", **record.to_dict()}
        with self._lock:
            self.action_records.append(record)
            self.history.append(entry)
            if self.log_path:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def active_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                event.to_dict()
                for event in self.events.values()
                if event.state.value in {"info", "warning", "critical"}
            ]

    def all_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [event.to_dict() for event in self.events.values()]

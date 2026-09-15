"""A fixed raw-frame ring with deterministic sampling and auditable retirement.

Every decoded frame is written. A retired/consumed slot is normal circular reuse;
overwriting an unread sequence divisible by four is a true selected-frame loss.
Only frame references and counters are manipulated while holding the ring lock.
"""
from __future__ import annotations

import queue
import threading
from time import perf_counter

from .models import FramePacket


class FrameRingBuffer:
    CAPACITY = 15

    def __init__(self, capacity=15):
        if capacity != self.CAPACITY:
            raise ValueError('ESE-CPU2 requires exactly 15 raw frame slots')
        self.maxsize = capacity
        self._slots = [None] * capacity
        self._selected = [False] * capacity
        self._lock = threading.Lock()
        self._last_sequence = -1
        self._writes = self._reads = self._skips = self._selected_writes = 0
        self._rotations = self._overruns = self._max_occupancy = 0
        self._occupancy_sum = self._occupancy_samples = 0

    @staticmethod
    def should_select(sequence):
        return sequence % 4 == 0

    def write(self, packet: FramePacket):
        """Return (selected, selected_frame_overwritten, buffer_write_timestamp)."""
        with self._lock:
            if packet.frame_id <= self._last_sequence:
                raise ValueError('Raw sequence must increase monotonically within a camera run')
            self._last_sequence = packet.frame_id
            index = packet.frame_id % self.maxsize
            overrun = self._slots[index] is not None and self._selected[index]
            if self._slots[index] is not None:
                self._rotations += 1
            if overrun:
                self._overruns += 1
            selected = self.should_select(packet.frame_id)
            self._slots[index] = packet
            self._selected[index] = selected
            self._writes += 1
            self._selected_writes += int(selected)
            self._skips += int(not selected)
            occupied = sum(item is not None for item in self._slots)
            self._max_occupancy = max(self._max_occupancy, occupied)
            self._occupancy_sum += occupied
            self._occupancy_samples += 1
            return selected, bool(overrun), perf_counter()

    def get_nowait(self):
        """Consume the oldest retained selected frame, then release its raw slot."""
        with self._lock:
            indices = [i for i, selected in enumerate(self._selected) if selected]
            if not indices:
                raise queue.Empty
            index = min(indices, key=lambda i: self._slots[i].frame_id)
            packet = self._slots[index]
            self._slots[index] = None
            self._selected[index] = False
            self._reads += 1
            return packet

    def empty(self):
        with self._lock:
            return not any(self._selected)

    def qsize(self):
        with self._lock:
            return sum(item is not None for item in self._slots)

    def snapshot(self):
        with self._lock:
            return dict(capacity=self.maxsize, writes=self._writes, reads=self._reads,
                intentional_skips=self._skips, selected=self._selected_writes,
                circular_reuses=self._rotations, normal_reuses=self._rotations-self._overruns,
                true_overruns=self._overruns, pending_selected=sum(self._selected),
                final_occupancy=sum(item is not None for item in self._slots),
                max_occupancy=self._max_occupancy,
                mean_occupancy_per_write=self._occupancy_sum / max(1,self._occupancy_samples))

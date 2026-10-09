"""Scoped Python network prohibition for an exclusively local dataset workflow."""
from __future__ import annotations

import socket
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import patch


@dataclass
class NetworkAudit:
    """Actual attempted socket connections, not a hardcoded success counter."""
    attempts: int = 0


@contextmanager
def no_network() -> Iterator[NetworkAudit]:
    """Block connect/connect_ex for this scope and restore them on exit."""
    audit=NetworkAudit()
    def reject(*args: object, **kwargs: object) -> None:
        audit.attempts+=1
        raise OSError('QCI-1 offline run forbids network connections')
    with patch.object(socket.socket,'connect',reject),patch.object(socket.socket,'connect_ex',reject):yield audit

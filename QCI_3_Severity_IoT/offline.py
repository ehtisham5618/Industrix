"""Process-local test guard blocks external TCP while allowing loopback HTTP."""
from contextlib import contextmanager
import ipaddress
import socket
from unittest.mock import patch

@contextmanager
def loopback_only():
    original=socket.socket.connect;attempts=[]
    def guarded(sock,address):
        if sock.family in (socket.AF_INET,socket.AF_INET6):
            try:allowed=ipaddress.ip_address(address[0]).is_loopback
            except ValueError:allowed=False
            if not allowed:
                attempts.append(str(address[0]));raise OSError('External TCP blocked for offline verification')
        return original(sock,address)
    with patch.object(socket.socket,'connect',guarded):yield attempts

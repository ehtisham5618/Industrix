"""Validation-only local server: reject every non-loopback Python TCP connect."""
import ipaddress
import socket
import sys
import traceback
import uvicorn

connect=socket.socket.connect
def loopback_connect(sock,address):
    if isinstance(address,tuple):
        host=str(address[0])
        try:local=ipaddress.ip_address(host).is_loopback
        except ValueError:local=host=='localhost'
        if not local:
            print('EXTERNAL_NETWORK_BLOCKED host='+host+' trace='+str([(s.filename,s.name) for s in traceback.extract_stack(limit=30)]),flush=True)
            raise OSError('External network disabled for offline incident validation')
    return connect(sock,address)

socket.socket.connect=loopback_connect
if __name__=='__main__':uvicorn.run('Backend.main:api_app',host='127.0.0.1',port=8000,log_level='info')

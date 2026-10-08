"""Guard every Python TCP connection, including connect_ex, before app imports."""
import ipaddress
import socket
import os
import json
import time
from pathlib import Path

def install_guard():
    connect=socket.socket.connect;connect_ex=socket.socket.connect_ex
    def check(address):
        if not isinstance(address,tuple):return
        host=str(address[0])
        try:local=ipaddress.ip_address(host).is_loopback
        except ValueError:local=host=='localhost'
        if not local:
            item=dict(timestamp=time.time(),host=host,blocked=True)
            journal=os.getenv('DEMO_NETWORK_JOURNAL')
            if journal:
                with Path(journal).open('a',encoding='utf-8') as out:out.write(json.dumps(item)+'\n')
            raise OSError('Non-loopback TCP disabled for local demo')
    def guarded(sock,address):check(address);return connect(sock,address)
    def guarded_ex(sock,address):check(address);return connect_ex(sock,address)
    socket.socket.connect=guarded;socket.socket.connect_ex=guarded_ex

if __name__=='__main__':
    install_guard()
    import sys
    if '--frontend' in sys.argv:
        from streamlit.web import cli
        sys.argv=['streamlit','run','Frontend/app.py','--server.port','8501','--server.address','127.0.0.1','--browser.gatherUsageStats','false']
        cli.main()
    else:
        import uvicorn
        uvicorn.run('Backend.main:api_app',host='127.0.0.1',port=8000,log_level='info')

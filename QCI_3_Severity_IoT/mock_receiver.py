"""Safe loopback receiver: records JSON and deduplicates software activations."""
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
import time

class MockReceiver:
    def __init__(self,codes=(200,),ack=True,delay=0,drop=False):
        self.codes=deque(codes);self.ack=ack;self.delay=delay;self.drop=drop
        self.received=[];self.activations=set();self.lock=threading.Lock()
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=32768:self.send_error(413);return
                payload=json.loads(self.rfile.read(size))
                with owner.lock:
                    if len(owner.received)>=10000:self.send_error(503);return
                    owner.received.append({'payload':payload,'idempotency_key':self.headers.get('Idempotency-Key')})
                    code=owner.codes.popleft() if len(owner.codes)>1 else owner.codes[0]
                    if code==200:owner.activations.add(payload['delivery_id'])
                if owner.drop:self.close_connection=True;return
                if owner.delay:time.sleep(owner.delay)
                body=json.dumps({'delivery_id':payload['delivery_id'],'acknowledged':True} if owner.ack else {'accepted':True}).encode()
                try:
                    self.send_response(code);self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                except OSError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='qci3-loopback-mock',daemon=False)
        self.url=f'http://127.0.0.1:{self.server.server_port}/siren'

    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)

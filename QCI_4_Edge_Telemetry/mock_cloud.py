"""Loopback-only service with durable dedupe receipts and injectable network failures."""
from collections import deque
from contextlib import closing
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading
import time
from .spool import ADAPTER

class MockCloud:
    def __init__(self,database,port=0,capture_capacity=10000):
        self.database=Path(database);self.database.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS receipts(dedupe TEXT PRIMARY KEY,digest TEXT NOT NULL,item TEXT NOT NULL,payload TEXT NOT NULL)');db.commit()
        self.lock=threading.RLock();self.health_online=True;self.codes=deque([200]);self.delay=0
        self.bad_ack=False;self.malformed=False;self.drop=False;self.retry_after=None;self.accept_before_response=False;self.trickle_headers=0
        self.attempts=deque(maxlen=capture_capacity);self.attempt_count=0;self.health_requests=0;self.oversized=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,code,data):
                raw=b'not JSON' if owner.malformed else b'x'*8193 if owner.oversized else json.dumps(data).encode()
                try:
                    if owner.trickle_headers:
                        header=f'HTTP/1.0 {code} Test\r\nContent-Length: {len(raw)}\r\n\r\n'.encode()
                        for byte in header:
                            self.connection.sendall(bytes([byte]));time.sleep(owner.trickle_headers)
                        self.connection.sendall(raw);return
                    self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                    if owner.retry_after is not None:self.send_header('Retry-After',str(owner.retry_after))
                    self.end_headers();self.wfile.write(raw)
                except OSError:pass
            def do_GET(self):
                if self.path!='/health':self.reply(404,{});return
                with owner.lock:owner.health_requests+=1;online=owner.health_online
                self.reply(200 if online else 503,{'status':'ok' if online else 'unavailable','service':'qci4-sync-v1'})
            def do_POST(self):
                if self.path!='/sync':self.reply(404,{});return
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=16384:raise ValueError('Oversized request')
                    body=json.loads(self.rfile.read(length));ADAPTER.validate_python(body['payload'])
                    digest=hashlib.sha256(json.dumps(body['payload'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
                    if digest!=body['payload_sha256'] or self.headers.get('Idempotency-Key')!=body['dedupe_key']:raise ValueError('Invalid delivery contract')
                except (ValueError,KeyError,TypeError):self.reply(400,{});return
                with owner.lock:
                    code=owner.codes.popleft() if len(owner.codes)>1 else owner.codes[0]
                    owner.attempts.append({'body':body,'code':code,'idempotency_key':self.headers.get('Idempotency-Key')})
                    owner.attempt_count+=1
                    if 200<=code<300 or owner.accept_before_response:
                        with closing(sqlite3.connect(owner.database)) as db:
                            old=db.execute('SELECT digest FROM receipts WHERE dedupe=?',(body['dedupe_key'],)).fetchone()
                            if old and old[0]!=digest:code=409
                            else:db.execute('INSERT OR IGNORE INTO receipts VALUES(?,?,?,?)',(body['dedupe_key'],digest,body['item_id'],json.dumps(body['payload'])));db.commit()
                if owner.drop:self.close_connection=True;return
                if owner.delay:time.sleep(owner.delay)
                ack={'item_id':body['item_id'],'dedupe_key':body['dedupe_key'],'payload_sha256':body['payload_sha256'],'accepted':not owner.bad_ack}
                self.reply(code,ack)
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='qci4-mock-cloud',daemon=False)
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def receipts(self):
        with closing(sqlite3.connect(self.database)) as db:return db.execute('SELECT dedupe,digest,item,payload FROM receipts ORDER BY rowid').fetchall()
    def receipt_count(self):
        with closing(sqlite3.connect(self.database)) as db:return db.execute('SELECT COUNT(*) FROM receipts').fetchone()[0]

"""Disposable stdlib HTTP service for watchdog tests (never the real backend).

python dummy_service.py PORT CONTROL_DIR
  /health -> 200 {"model_loaded": true}; 503 while CONTROL_DIR/unhealthy exists.
  Exits with code 9 as soon as CONTROL_DIR/crash exists (the file is consumed).
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT, CONTROL = int(sys.argv[1]), Path(sys.argv[2])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        ok = not (CONTROL / "unhealthy").exists()
        body = json.dumps({"status": "ok" if ok else "degraded", "model_loaded": ok}).encode()
        self.send_response(200 if ok else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def crash_watch():
    while True:
        if (CONTROL / "crash").exists():
            (CONTROL / "crash").unlink()
            print("dummy service crashing on request", flush=True)
            import os
            os._exit(9)
        time.sleep(0.1)


threading.Thread(target=crash_watch, daemon=True).start()
print(f"dummy service listening on {PORT}", flush=True)
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

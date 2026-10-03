"""
Tiny stdlib HTTP server, only used when KEEP_ALIVE=true.

Needed on hosts like Render that require an open HTTP port and spin the
service down when no requests arrive. Point UptimeRobot (or any cron pinger)
at the service URL every 5-10 minutes.

Not needed on Discloud / HeavenCloud / Oracle / a VPS — leave KEEP_ALIVE unset.
"""

from __future__ import annotations

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("partnership.keepalive")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b'{"status":"ok","service":"partnership-bot"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):  # silence per-request logging
        pass


def start() -> None:
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="keep-alive")
    thread.start()
    log.info("Keep-alive HTTP server listening on 0.0.0.0:%d", port)

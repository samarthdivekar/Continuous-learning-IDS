"""Presentation layer without nginx: serve dashboard/ and proxy /api/* to the API.

    python scripts/dashboard_server.py --port 8080 --api http://127.0.0.1:8000

Same routing contract as docker/nginx.conf, so the dashboard code is identical
in both deployments.
"""
from __future__ import annotations

import argparse
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-encoding", "content-length"}


class Handler(SimpleHTTPRequestHandler):
    api_base = "http://127.0.0.1:8000"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "dashboard"), **kw)

    def end_headers(self):
        # always revalidate: the console is edited live and ES modules are cached aggressively
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(self.api_base + self.path[len("/api"):], data=body, method=method)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                payload, status, headers = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:            # forward API error responses verbatim
            payload, status, headers = e.read(), e.code, e.headers
        except urllib.error.URLError as e:
            payload, status, headers = f'{{"detail":"API unreachable: {e.reason}"}}'.encode(), 503, {}
        self.send_response(status)
        for k, v in (headers.items() if headers else []):
            if k.lower() not in HOP_BY_HOP:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._proxy("GET") if self.path.startswith("/api/") else super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(405)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--api", default="http://127.0.0.1:8000")
    a = p.parse_args()
    Handler.api_base = a.api.rstrip("/")
    print(f"dashboard on http://localhost:{a.port}/  ->  api {Handler.api_base}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), partial(Handler)).serve_forever()


if __name__ == "__main__":
    main()

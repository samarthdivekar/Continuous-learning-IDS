"""Presentation layer without nginx: serve dashboard/ and proxy /api/* to the API.

    python scripts/dashboard_server.py --port 8080 --api http://127.0.0.1:8000

The dashboard calls the API under /api on its own origin, so it never needs to know
where the API runs.
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
# Chart.js and d3 come from jsdelivr (see dashboard/index.html); everything else is local.
CSP = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


class Handler(SimpleHTTPRequestHandler):
    api_base = "http://127.0.0.1:8000"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "dashboard"), **kw)

    def end_headers(self):
        # always revalidate: the console is edited live and ES modules are cached aggressively
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        for header, value in SECURITY_HEADERS.items():
            self.send_header(header, value)
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter console: API calls and errors only
        # args[0] is the request line for access logs but an HTTPStatus for send_error(); treating it as
        # a string crashed the handler, so every 404 reached the browser as an empty reply
        first = str(args[0]) if args else ""
        if "/api/" in first or fmt.startswith("code "):
            super().log_message(fmt, *args)

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(self.api_base + self.path[len("/api"):], data=body, method=method)
        for header in ("Content-Type", "X-API-Key"):      # the key must survive the proxy hop
            if self.headers.get(header):
                req.add_header(header, self.headers[header])
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

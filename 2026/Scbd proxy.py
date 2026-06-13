#!/usr/bin/env python3
"""
DASH SCBD Dashboard — local proxy server
Zero external dependencies (stdlib only).

Usage:
    python scbd_proxy.py            # http://localhost:8765
    python scbd_proxy.py 9000       # custom port

From Jupyter:
    import subprocess, webbrowser
    proc = subprocess.Popen(["python", "scbd_proxy.py"])
    webbrowser.open("http://localhost:8765")
"""
import http.server
import http.client
import urllib.parse
import json
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer

PORT      = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
API_HOST  = "api.unimelb-dash.com"
HTML_FILE = Path(__file__).parent / "scbd_dashboard.html"

# Headers that must not be forwarded (hop-by-hop)
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te",
               "trailer", "upgrade", "proxy-authorization", "proxy-authenticate"}


class Handler(http.server.BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/dashboard", "/scbd_dashboard.html"):
            self._serve_html()
        elif parsed.path.startswith("/api/"):
            self._proxy(parsed)
        else:
            self.send_response(404)
            self.end_headers()

    # ── Serve dashboard HTML ──────────────────────────────────────────────────
    def _serve_html(self):
        if not HTML_FILE.exists():
            msg = f"scbd_dashboard.html not found in {HTML_FILE.parent}".encode()
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        data = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── Proxy to DASH API via http.client (no urllib middleware) ──────────────
    def _proxy(self, parsed):
        # /api/assessment/scbd/... → /assessment/scbd/...
        upstream_path = parsed.path[4:]
        if parsed.query:
            upstream_path += "?" + parsed.query

        # Forward browser headers directly — skip hop-by-hop and Host
        fwd = {k: v for k, v in self.headers.items()
               if k.lower() not in HOP_BY_HOP and k.lower() != "host"}

        # Debug: log sanitized token so you can verify it's arriving correctly
        auth = fwd.get("Authorization", fwd.get("authorization", ""))
        if auth:
            preview = auth[:20] + "…" if len(auth) > 20 else auth
            print(f"  → Forwarding auth: {preview}")
        else:
            print(f"  ⚠  No Authorization header received from browser")

        conn = http.client.HTTPSConnection(API_HOST, timeout=60)
        try:
            conn.request("GET", upstream_path, headers=fwd)
            resp = conn.getresponse()
            body = resp.read()
            ct   = resp.getheader("Content-Type", "application/json")
            body = self._rewrite_next(body, ct)
            print(f"  [{resp.status}] {upstream_path[:70]}")
            self._send(resp.status, ct, body)
        except Exception as e:
            print(f"  [ERR] {e}")
            body = json.dumps({"error": str(e)}).encode()
            self._send(502, "application/json", body)
        finally:
            conn.close()

    def _rewrite_next(self, body, ct):
        """Rewrite upstream host in 'next' pagination URLs → /api/..."""
        if "json" not in ct or not body:
            return body
        try:
            d = json.loads(body)
            if isinstance(d, dict) and d.get("next"):
                d["next"] = d["next"].replace(f"https://{API_HOST}", "/api")
                return json.dumps(d).encode()
        except Exception:
            pass
        return body

    def _send(self, status, ct, body):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  f"http://localhost:{PORT}")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")

    def log_message(self, fmt, *args):
        pass  # handled in _proxy


if __name__ == "__main__":
    bar = "─" * 46
    print(f"\n  DASH · SCBD Proxy (http.client mode)\n  {bar}")
    print(f"  Dashboard  →  http://localhost:{PORT}/")
    print(f"  Proxying   →  localhost:{PORT}/api → https://{API_HOST}")
    print(f"  HTML file  →  {HTML_FILE}")
    if not HTML_FILE.exists():
        print(f"\n  ⚠  scbd_dashboard.html not found — place it next to this script")
    print(f"\n  Ctrl+C to stop\n")
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
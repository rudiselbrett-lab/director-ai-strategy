#!/usr/bin/env python3
"""Serve the command center with a working "Refresh from Jira" button.

The page cannot call Jira itself: Jira Cloud refuses calls from a web page
(CORS), and a token inside a page is a token in a file that gets forwarded.
So this runs on your machine, holds the token in its environment, and the
button asks it to pull. Only the issues reach the page, trimmed to the
fields the command center reads, people cut to display names.

    export JIRA_SITE=https://yourbank.atlassian.net
    export JIRA_EMAIL=you@yourbank.com JIRA_API_TOKEN=...    # Jira Cloud
    # or: export JIRA_PAT=...                                # Data Center
    export JIRA_JQL='project = AIUC ORDER BY key'             # optional
    python3 cowork/serve.py                                   # then open the URL it prints

Listens on 127.0.0.1 only. Needs build_portfolio.py one folder up.
Behind a TLS-inspecting proxy, set SSL_CERT_FILE to the bank's CA bundle.
"""
import argparse
import json
import os
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build_portfolio as bp  # noqa: E402

PAGE = HERE / "command-center.html"


def make_handler(jmap, jql, port):
    allowed = {"127.0.0.1:%d" % port, "localhost:%d" % port}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *a):
            sys.stderr.write("  %s\n" % (fmt % a))

        def _send(self, code, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            # Another site in your browser cannot reach this through a
            # renamed host (DNS rebinding): only the address we bound answers.
            if self.headers.get("Host") not in allowed:
                return self._send(403, {"error": "forbidden host"})
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/refresh":
                try:
                    snap = bp.fetch_jira(jmap, jql=jql, log=lambda m: sys.stderr.write(m + "\n"))
                except bp.JiraError as e:
                    return self._send(502, {"error": str(e)})
                return self._send(200, snap)
            self._send(404, {"error": "not found"})

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="Serve the command center with live Jira refresh.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--jira-map", metavar="FILE", help="JIRA_MAP JSON (default: the generic map)")
    args = ap.parse_args(argv)
    jmap = (json.loads(pathlib.Path(args.jira_map).read_text(encoding="utf-8"))
            if args.jira_map else bp.builtin_data()["JIRA_MAP"])
    jmap = dict(jmap, includeText=False)
    jql = os.environ.get("JIRA_JQL")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(jmap, jql, args.port))
    print("command center: http://127.0.0.1:%d   (Ctrl+C to stop)" % args.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

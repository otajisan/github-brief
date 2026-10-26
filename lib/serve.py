#!/usr/bin/env python3
"""Loopback-only static server for the history hub (used by scripts/serve.sh).

Stricter than `python3 -m http.server`, because it may run all session long as
the com.github-brief.serve login item:

- binds 127.0.0.1 only, and answers 403 unless the Host header names this
  machine — a DNS-rebinding page cannot read the briefs through the browser;
- serves only the brief pages (*.html); logs/, the *.json sidecars (raw PR
  bodies) and directory listings are 404;
- sends a CSP that forbids scripts and outbound requests, so a page the model
  was tricked into writing (prompt injection via a PR body) cannot read the
  other briefs and send them anywhere;
- writes no per-request access log, so the launchd log does not grow forever.

usage: serve.py <port> <directory>
"""
import functools
import http.server
import sys
import urllib.parse

ALLOWED_HOSTS = ("localhost", "127.0.0.1")
SERVED_SUFFIX = ".html"
# Pages are self-contained HTML + inline CSS (see the prompt templates).
SECURITY_HEADERS = (
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
     "base-uri 'none'; form-action 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
)


class BriefHandler(http.server.SimpleHTTPRequestHandler):
    def _allowed(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            self.send_error(403)
            return False
        path = urllib.parse.unquote(self.path.split("?", 1)[0].split("#", 1)[0])
        if path == "/":
            self.path = "/index.html"
        elif "/" in path[1:] or "\x00" in path or not path.endswith(SERVED_SUFFIX):
            self.send_error(404)
            return False
        return True

    def do_GET(self) -> None:
        if self._allowed():
            super().do_GET()

    def do_HEAD(self) -> None:
        if self._allowed():
            super().do_HEAD()

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def list_directory(self, path: str) -> None:
        self.send_error(404)
        return None

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[-1])
    port, directory = int(sys.argv[1]), sys.argv[2]
    handler = functools.partial(BriefHandler, directory=directory)
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Serving {directory} at http://localhost:{port}/index.html", flush=True)
        httpd.serve_forever()


if __name__ == "__main__":
    main()

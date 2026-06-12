#!/usr/bin/env python3
"""Minimal HTTP endpoint that accepts exfil uploads from wget/curl."""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class ExfilReceiver(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[receiver] {self.address_string()} - {fmt % args}", flush=True)

    def do_GET(self) -> None:
        if self.path in {"/", "/health", "/upload"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        tool = self.headers.get("User-Agent", "unknown")
        print(
            f"[receiver] POST {self.path} bytes={len(body)} agent={tool!r}",
            flush=True,
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_PUT(self) -> None:
        self.do_POST()


def main() -> None:
    host = os.environ.get("EXFIL_RECEIVER_HOST", "0.0.0.0")
    port = int(os.environ.get("EXFIL_RECEIVER_PORT", "8888"))
    server = HTTPServer((host, port), ExfilReceiver)
    print(f"Exfil receiver listening on http://{host}:{port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

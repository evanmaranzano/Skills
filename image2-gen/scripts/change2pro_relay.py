#!/usr/bin/env python3
"""Lightweight local relay for Change2Pro image generation requests.

Purpose:
- Accept local POST requests compatible with OpenAI-style image generations
- Forward them to https://api.change2pro.com/v1/images/generations
- Return the upstream response body and status code unchanged as much as possible

This is a fallback helper for environments where the primary caller's network
stack or client fingerprint is blocked, but a local background relay may work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request


UPSTREAM_URL = "https://api.change2pro.com/v1/images/generations"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5099
DEFAULT_API_KEY = "sk-5205fac8ce75120857f304d610e326d64eed7b5bb6674c4bce19da2604e554d8"


def build_opener() -> request.OpenerDirector:
    """Honor proxy environment variables if present."""
    return request.build_opener()


def make_handler(api_key: str, log_file: Path | None):
    opener = build_opener()

    class RelayHandler(BaseHTTPRequestHandler):
        server_version = "Change2ProRelay/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            message = fmt % args
            if log_file is not None:
                log_file.parent.mkdir(parents=True, exist_ok=True)
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(message + "\n")
            else:
                sys.stderr.write(message + "\n")

        def _write_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._write_json(200, {"ok": True, "upstream": UPSTREAM_URL})
                return
            self._write_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path not in ("/generate", "/v1/images/generations"):
                self._write_json(404, {"error": "not found"})
                return

            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw_body = self.rfile.read(content_length)

            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception as exc:
                self._write_json(400, {"error": f"invalid json: {exc}"})
                return

            upstream_req = request.Request(
                UPSTREAM_URL,
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "change2pro-local-relay/1.0",
                },
                method="POST",
            )

            try:
                with opener.open(upstream_req, timeout=180) as resp:
                    upstream_body = resp.read()
                    self.send_response(resp.status)
                    self.send_header(
                        "Content-Type",
                        resp.headers.get("Content-Type", "application/json"),
                    )
                    self.send_header("Content-Length", str(len(upstream_body)))
                    self.end_headers()
                    self.wfile.write(upstream_body)
            except error.HTTPError as exc:
                body = exc.read()
                self.send_response(exc.code)
                self.send_header(
                    "Content-Type",
                    exc.headers.get("Content-Type", "application/json"),
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self._write_json(
                    502,
                    {
                        "error": "relay_request_failed",
                        "detail": str(exc),
                    },
                )

    return RelayHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Change2Pro lightweight local relay")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CHANGE2PRO_API_KEY", DEFAULT_API_KEY),
        help="Change2Pro API key",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional log file path",
    )
    args = parser.parse_args()

    handler = make_handler(args.api_key, args.log_file)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Relay listening on http://{args.host}:{args.port}", flush=True)
    print(f"Forwarding to {UPSTREAM_URL}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Relay stopped", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

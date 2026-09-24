"""Loopback-only, explicitly launched workbench; no persistent server or remote auth."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from .api import dispatch
from .errors import NmrError
from .service import Service

MAX_BODY = 1024 * 1024


def make_http(service: Service, port=0):
    token = secrets.token_urlsafe(32)
    static = Path(__file__).with_name("static")

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args):
            pass  # Do not log session tokens, original paths or scientific content.

        def send(self, status, body, kind="application/json"):
            if isinstance(body, dict):
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, *, download=False):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != host:
                return False
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                return False
            candidate = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return candidate.isascii() and hmac.compare_digest(candidate, token)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in {"/", "/app.js", "/app.css"}:
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    self.send(403, {"error": "HOST_REJECTED"})
                    return
                name = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css"}[path]
                kind = {
                    "index.html": "text/html; charset=utf-8",
                    "app.js": "text/javascript; charset=utf-8",
                    "app.css": "text/css; charset=utf-8",
                }[name]
                self.send(200, (static / name).read_bytes(), kind)
                return
            download = path.startswith("/api/artifact/")
            if not self.allowed(download=download):
                self.send(403, {"error": "SESSION_REQUIRED"})
                return
            try:
                if path == "/api/project":
                    self.send(200, service.read().model_dump(mode="json"))
                elif download:
                    meta, data = service.store.artifact(path.rsplit("/", 1)[-1])
                    self.send(200, data, meta.media_type)
                else:
                    self.send(404, {"error": "NOT_FOUND"})
            except NmrError as exc:
                self.send(400, {"error": {"code": exc.code, "message": exc.message}})

        def do_POST(self):
            if not self.allowed():
                self.send(403, {"error": "SESSION_REQUIRED"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_BODY:
                    self.send(413, {"error": "BODY_LIMIT"})
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.send(415, {"error": "JSON_REQUIRED"})
                    return
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict) or set(data) != {"name", "arguments"}:
                    raise ValueError("Expected name and arguments.")
                if urlsplit(self.path).path != "/api/tool":
                    self.send(404, {"error": "NOT_FOUND"})
                    return
                result = dispatch(service, data["name"], data["arguments"])
                self.send(200, result)
            except (ValueError, TypeError, NmrError) as exc:
                self.send(
                    400,
                    {
                        "error": {
                            "code": getattr(exc, "code", "INVALID_REQUEST"),
                            "message": getattr(
                                exc, "message", "Request is not valid JSON tool input."
                            ),
                        }
                    },
                )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = False
    return server, token


def run(service, port=0):
    server, token = make_http(service, port)
    print(f"http://127.0.0.1:{server.server_port}/#token={token}", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

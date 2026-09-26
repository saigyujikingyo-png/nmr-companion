"""Loopback-only, explicitly launched workbench; no persistent server or remote auth."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
import threading
import hashlib
import re
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
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; base-uri 'none'",
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
            if path in {
                "/",
                "/app.js",
                "/view.js",
                "/app.css",
                "/batch.js",
                "/batch.css",
                "/InterVariable.woff2",
            }:
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    self.send(403, {"error": "HOST_REJECTED"})
                    return
                name = "index.html" if path == "/" else path[1:]
                kind = {
                    "index.html": "text/html; charset=utf-8",
                    "batch.js": "text/javascript; charset=utf-8",
                    "batch.css": "text/css; charset=utf-8",
                    "app.js": "text/javascript; charset=utf-8",
                    "app.css": "text/css; charset=utf-8",
                    "view.js": "text/javascript; charset=utf-8",
                    "InterVariable.woff2": "font/woff2",
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
                elif match := re.fullmatch(r"/api/source/([a-f0-9]{64})", path):
                    with service.store.connection() as db:
                        db.execute("BEGIN")
                        project = service.store.read_from(db)
                        digest = match[1]
                        if digest not in project.sources:
                            raise NmrError(
                                "NOT_FOUND", "Source does not belong to this project revision."
                            )
                        row = db.execute(
                            "SELECT data FROM originals WHERE sha256=?", (digest,)
                        ).fetchone()
                        if row is None or hashlib.sha256(row[0]).hexdigest() != digest:
                            raise NmrError(
                                "SOURCE_INTEGRITY", "Original source is missing or corrupt."
                            )
                        kind = next(
                            (
                                a.media_type
                                for a in project.attachments.values()
                                if a.source_id == digest
                            ),
                            "application/octet-stream",
                        )
                    self.send(200, row[0], kind)
                elif match := re.fullmatch(
                    r"/api/reference/([A-Za-z0-9_-]+)/page/([0-9]{1,4})", path
                ):
                    from .media import reference_png

                    with service.store.connection() as db:
                        db.execute("BEGIN")
                        project = service.store.read_from(db)
                        attachment = project.attachments.get(match[1])
                        page_number = int(match[2])
                        if attachment is None:
                            raise NmrError("NOT_FOUND", "Reference attachment does not exist.")
                        if not 1 <= page_number <= attachment.pages:
                            raise NmrError("REFERENCE_PAGE", "Reference page does not exist.")
                        row = db.execute(
                            "SELECT data FROM originals WHERE sha256=?", (attachment.source_id,)
                        ).fetchone()
                        if (
                            row is None
                            or hashlib.sha256(row[0]).hexdigest() != attachment.source_id
                        ):
                            raise NmrError(
                                "SOURCE_INTEGRITY", "Reference original is missing or corrupt."
                            )
                        data = reference_png(row[0], attachment.media_type, page_number)
                    self.send(200, data, "image/png")
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
            if urlsplit(self.path).path == "/api/quit":
                if self.headers.get("Content-Length", "0") != "0":
                    self.send(400, {"error": "EMPTY_BODY_REQUIRED"})
                    return
                self.send(200, {"ok": True, "state": "stopping"})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
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


def run(service, port=0, *, open_browser=False):
    server, token = make_http(service, port)
    url = f"http://127.0.0.1:{server.server_port}/#token={token}"
    print(url, flush=True)
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

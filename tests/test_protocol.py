import asyncio
from datetime import timedelta
import base64
import hashlib
import json
import os
import sys
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import jsonschema
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from nmr_companion.service import Service
from nmr_companion.web import make_http


def test_stdio_real_discovery_calls_errors_resources_and_eof(tmp_path):
    project = tmp_path / "protocol.nmrproj"

    async def scenario():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-c",
                "from nmr_companion.cli import main; main()",
                "--project",
                str(project),
                "mcp",
            ],
            env=os.environ.copy(),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=15)
            ) as session:
                await session.initialize()
                catalog = await session.list_tools()
                schemas = {tool.name: tool.outputSchema for tool in catalog.tools}
                assert len(schemas) == 6 and all(schemas.values())

                async def call(name, args):
                    result = await session.call_tool(name, args)
                    jsonschema.validate(result.structuredContent, schemas[name])
                    assert result.isError == (not result.structuredContent["ok"])
                    return result.structuredContent

                missing = await call("nmr_project", {})
                assert missing["error"]["code"] == "NO_PROJECT"
                created = await call("nmr_project", {"action": "create", "name": "Protocol"})
                assert created["data"]["revision"] == 0
                demo = await call(
                    "nmr_edit",
                    {"expected_revision": 0, "request_id": "mcp-demo", "command": {"op": "demo"}},
                )
                assert demo["data"]["revision"] == 1
                bad = await call(
                    "nmr_edit",
                    {"expected_revision": 0, "request_id": "stale", "command": {"op": "demo"}},
                )
                assert bad["error"]["code"] == "REVISION_CONFLICT"
                invalid = await call("nmr_export", {"revision": "not-an-integer"})
                assert invalid["error"]["code"] == "INVALID_ARGUMENT"
                receipt = await call("nmr_request", {"request_id": "mcp-demo"})
                assert receipt["data"]["revision"] == 1
                export = await call("nmr_export", {"revision": 1})
                resource = await session.read_resource(export["data"]["uri"])
                blob = base64.b64decode(resource.contents[0].blob)
                assert hashlib.sha256(blob).hexdigest() == export["data"]["sha256"]
        # stdio_client must terminate/reap its child on EOF; no background server is started.
        assert Service(project).read().revision == 1

    asyncio.run(scenario())


def test_http_token_origin_conflict_and_shared_mcp_state(tmp_path):
    service = Service(tmp_path / "web.nmrproj")
    service.create("Web")
    server, token = make_http(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, *, body=None, auth=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer " + token
        if origin:
            headers["Origin"] = origin
        data = json.dumps(body).encode() if body is not None else None
        with urlopen(Request(base + path, data=data, headers=headers), timeout=10) as response:
            return json.loads(response.read())

    try:
        with pytest.raises(HTTPError) as failure:
            request("/api/project", auth=False)
        assert failure.value.code == 403
        with pytest.raises(HTTPError) as failure:
            request(
                "/api/tool",
                body={"name": "nmr_project", "arguments": {}},
                origin="https://foreign.invalid",
            )
        assert failure.value.code == 403
        edit = request(
            "/api/tool",
            body={
                "name": "nmr_edit",
                "arguments": {
                    "expected_revision": 0,
                    "request_id": "human-demo",
                    "command": {"op": "demo"},
                },
            },
        )
        assert edit["ok"]
        # A different frontend observes exactly the state committed through HTTP.
        second = Service(service.store.path)
        assert second.read().revision == 1
        sid = next(iter(second.read().spectra))
        second.apply(
            1, "agent-integral", {"op": "integrate", "spectrum_id": sid, "lower": 1.8, "upper": 2.2}
        )
        stale = request(
            "/api/tool",
            body={
                "name": "nmr_edit",
                "arguments": {
                    "expected_revision": 1,
                    "request_id": "human-stale",
                    "command": {"op": "peaks", "spectrum_id": sid, "prominence": 0.1},
                },
            },
        )
        assert not stale["ok"] and stale["error"]["code"] == "REVISION_CONFLICT"
        assert request("/api/project")["revision"] == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_offline_workbench_assets_and_host_boundary(tmp_path):
    service = Service(tmp_path / "static.nmrproj")
    server, token = make_http(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for path, media, marker in [
            ("/", "text/html", b'src="/view.js"'),
            ("/view.js", "text/javascript", b"NMRView"),
            ("/InterVariable.woff2", "font/woff2", b"wOF2"),
        ]:
            with urlopen(base + path, timeout=10) as response:
                body = response.read()
                assert response.headers.get_content_type() == media
                assert marker in body
                assert "default-src 'self'" in response.headers["Content-Security-Policy"]
                assert response.headers["X-Content-Type-Options"] == "nosniff"
                assert token.encode() not in body
            with pytest.raises(HTTPError) as failure:
                urlopen(Request(base + path, headers={"Host": "foreign.invalid"}), timeout=10)
            assert failure.value.code == 403
        # Adding a font and a geometry module must not expose arbitrary package files.
        with pytest.raises(HTTPError) as failure:
            urlopen(
                Request(base + "/../service.py", headers={"Authorization": "Bearer " + token}),
                timeout=10,
            )
        assert failure.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()

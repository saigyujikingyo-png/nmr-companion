from io import BytesIO
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image
import pytest

from nmr_companion.service import Service
from nmr_companion.web import make_http


def test_reference_preview_auth_page_bounds_and_explicit_shutdown(tmp_path):
    s = Service(tmp_path / "http.nmrproj")
    s.create("HTTP")
    sample = s.apply(
        0, "sample", {"op": "sample", "name": "Reference", "role": "reference"}
    ).object_ids[0]
    image = Image.new("RGB", (100, 60), "white")
    path = tmp_path / "reference.pdf"
    image.save(path, "PDF")
    attachment = s.apply(
        1,
        "attach",
        {
            "op": "attach",
            "sample_id": sample,
            "source_role": "reference",
            "category": "IR",
            "path": str(path),
        },
    ).object_ids[0]
    server, token = make_http(s)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, auth=True, method="GET", origin=None):
        headers = {"Authorization": "Bearer " + token} if auth else {}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(base + path, headers=headers, method=method), timeout=10)

    try:
        for route, method in (
            (f"/api/reference/{attachment}/page/1", "GET"),
            ("/api/quit", "POST"),
        ):
            with pytest.raises(HTTPError) as err:
                request(route, auth=False, method=method)
            assert err.value.code == 403
        with pytest.raises(HTTPError) as err:
            request("/api/quit", method="POST", origin="https://elsewhere.invalid")
        assert err.value.code == 403
        assert thread.is_alive()
        digest = s.read().attachments[attachment].source_id
        with request(f"/api/source/{digest}") as response:
            assert response.read() == path.read_bytes()
        with pytest.raises(HTTPError) as err:
            request(f"/api/source/{digest}", auth=False)
        assert err.value.code == 403
        with request(f"/api/reference/{attachment}/page/1") as response:
            with Image.open(BytesIO(response.read())) as preview:
                assert preview.width == 200 and preview.height == 120
            assert "blob:" in response.headers["Content-Security-Policy"]
        with pytest.raises(HTTPError) as err:
            request(f"/api/reference/{attachment}/page/2")
        assert err.value.code == 400
        with request("/api/quit", method="POST") as response:
            assert json.load(response) == {"ok": True, "state": "stopping"}
        thread.join(5)
        assert not thread.is_alive()
        assert Service(s.store.path).read().revision == 2
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        thread.join(5)

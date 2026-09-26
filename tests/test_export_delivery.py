"""Export delivery acceptance through the public API with isolated local projects."""

import errno
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from nmr_companion import api
from nmr_companion.models import Artifact
from nmr_companion.service import Service


@pytest.fixture
def service(tmp_path):
    instance = Service(tmp_path / "delivery.nmrproj")
    instance.create("Synthetic local delivery acceptance")
    return instance


def artifact_count(service):
    with service.store.connection() as db:
        return db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]


def assert_failure(reply, code):
    api.SPECS["nmr_export"][1].model_validate(reply)
    assert reply["ok"] is False and reply["data"] is None
    assert reply["error"]["code"] == code
    assert isinstance(reply["error"]["message"], str) and reply["error"]["message"]


@pytest.mark.parametrize("extra", [{}, {"destination": None}])
def test_export_without_destination_keeps_resource_uri_and_null_local_path(
    service, tmp_path, extra
):
    reply = api.dispatch(service, "nmr_export", {"revision": 0, **extra})
    assert reply["ok"] is True and reply["error"] is None
    data = reply["data"]
    assert data["local_path"] is None
    assert data["uri"] == "nmr://artifacts/" + data["id"]
    assert set(Artifact.model_fields).issubset(data)
    artifact, raw = service.store.artifact(data["id"])
    assert data["size"] == artifact.size == len(raw)
    assert data["sha256"] == artifact.sha256 == hashlib.sha256(raw).hexdigest()
    assert not list(tmp_path.glob("*.zip"))


def test_export_destination_delivers_exact_historical_revision_and_reopenable_zip(
    service, tmp_path
):
    original = b"delay_ms\n10\n20\n"
    source = tmp_path / "delays.csv"
    source.write_bytes(original)
    service.apply(0, "import_fixture", {"op": "import", "path": str(source)})
    historical = service.read()
    table_id = next(iter(historical.tables))
    service.apply(
        historical.revision,
        "later_sample",
        {"op": "sample", "name": "Later state", "role": "synthetic", "object_ids": [table_id]},
    )
    current = service.read()
    destination = tmp_path / "user_outputs" / "historical.zip"
    destination.parent.mkdir()
    reply = api.dispatch(
        service,
        "nmr_export",
        {"revision": historical.revision, "destination": str(destination)},
    )
    assert reply["ok"] is True and reply["error"] is None
    data = reply["data"]
    assert set(Artifact.model_fields).issubset(data)
    assert data["revision"] == historical.revision
    assert data["local_path"] == str(destination.resolve())
    assert Path(data["local_path"]).is_absolute()
    assert data["media_type"] == "application/zip"
    assert data["uri"] == "nmr://artifacts/" + data["id"]
    raw = destination.read_bytes()
    assert data["size"] == len(raw) == destination.stat().st_size
    assert data["sha256"] == hashlib.sha256(raw).hexdigest()
    metadata, stored = service.store.artifact(data["id"])
    assert stored == raw and metadata.uri == data["uri"]
    reopened_path = tmp_path / "reopened.nmrproj"
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("project.json")) == historical.model_dump(mode="json")
        assert archive.read("originals/" + hashlib.sha256(original).hexdigest()) == original
        reopened_path.write_bytes(archive.read("project.nmrproj"))
    assert Service(reopened_path).read() == historical
    assert service.read() == current


@pytest.mark.parametrize("existing_bytes", [b"", b"User-owned destination bytes must survive."])
def test_existing_destination_is_rejected_before_artifact_generation(
    service, tmp_path, existing_bytes
):
    source = tmp_path / "delays.csv"
    source.write_bytes(b"delay_ms\n10\n")
    service.apply(0, "import_fixture", {"op": "import", "path": str(source)})
    # A real attempt to generate this artifact would fail SOURCE_INTEGRITY.
    # FILE_EXISTS must win without starting generation or creating an artifact.
    with service.store.connection() as db:
        db.execute("UPDATE originals SET data=?", (b"Deliberately corrupt synthetic fixture",))
        db.commit()
    destination = tmp_path / "occupied.zip"
    destination.write_bytes(existing_bytes)
    count = artifact_count(service)
    before = service.read()
    reply = api.dispatch(
        service,
        "nmr_export",
        {"revision": before.revision, "destination": str(destination)},
    )
    assert_failure(reply, "FILE_EXISTS")
    assert destination.read_bytes() == existing_bytes
    assert artifact_count(service) == count
    assert service.read() == before


@pytest.mark.parametrize(
    "case,code",
    [
        ("relative", "INVALID_PATH"),
        ("wrong_extension", "INVALID_PATH"),
        ("missing_parent", "INVALID_PATH"),
        ("parent_is_file", "INVALID_PATH"),
        ("empty", "INVALID_ARGUMENT"),
        ("too_long", "INVALID_ARGUMENT"),
        ("not_string", "INVALID_ARGUMENT"),
    ],
)
def test_export_rejects_invalid_destinations_without_creating_parent_directories(
    service, tmp_path, monkeypatch, case, code
):
    monkeypatch.chdir(tmp_path)
    destinations = {
        "relative": "relative.zip",
        "wrong_extension": str(tmp_path / "export.csv"),
        "missing_parent": str(tmp_path / "missing" / "export.zip"),
        "parent_is_file": str(tmp_path / "file_parent" / "export.zip"),
        "empty": "",
        "too_long": "x" * 4097,
        "not_string": 12,
    }
    (tmp_path / "file_parent").write_bytes(b"Existing parent is a regular file.")
    count = artifact_count(service)
    reply = api.dispatch(service, "nmr_export", {"revision": 0, "destination": destinations[case]})
    assert_failure(reply, code)
    assert not (tmp_path / "missing").exists()
    assert not (tmp_path / "export.csv").exists()
    assert not (tmp_path / "relative.zip").exists()
    assert (tmp_path / "file_parent").read_bytes() == b"Existing parent is a regular file."
    assert artifact_count(service) == count


@pytest.mark.parametrize("kind", ["target", "ancestor", "dangling_target"])
def test_export_rejects_symbolic_target_or_ancestor_when_platform_supports_links(
    service, tmp_path, kind
):
    target = tmp_path / "actual_target.zip"
    target.write_bytes(b"Original link target.")
    if kind == "ancestor":
        actual_directory = tmp_path / "actual_directory"
        actual_directory.mkdir()
        link = tmp_path / "linked_directory"
        destination = link / "export.zip"
        linked_target = actual_directory
    else:
        link = destination = tmp_path / "linked_target.zip"
        linked_target = tmp_path / "absent_target.zip" if kind == "dangling_target" else target
    try:
        link.symlink_to(linked_target, target_is_directory=kind == "ancestor")
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP} or getattr(
            exc, "winerror", None
        ) in {5, 1314}:
            pytest.skip("This platform does not permit creating a synthetic symbolic link.")
        raise
    count = artifact_count(service)
    reply = api.dispatch(service, "nmr_export", {"revision": 0, "destination": str(destination)})
    assert_failure(reply, "INVALID_PATH")
    assert link.is_symlink()
    assert target.read_bytes() == b"Original link target."
    assert not (tmp_path / "absent_target.zip").exists()
    if kind == "ancestor":
        assert not (actual_directory / "export.zip").exists()
    assert artifact_count(service) == count

"""Release builder boundaries and real Windows installer behavior in temp roots."""
import ctypes
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "packaging" / "windows" / "resources"
spec = importlib.util.spec_from_file_location("nmr_bundle_builder", ROOT / "scripts" / "build_windows_bundle.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Actual Windows PowerShell installer")
POWERSHELL = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")


def archive(tmp_path, entries):
    path = tmp_path / "runtime.tar.gz"
    with tarfile.open(path, "w:gz") as stream:
        for name, data, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
    return path


@pytest.mark.parametrize("name", ["python/../../outside", "python/C:/outside", "python/CON.txt", "python/a\\b", "python/a. /b"])
def test_runtime_extraction_rejects_windows_unsafe_paths(tmp_path, name):
    source = archive(tmp_path, [(name, b"unsafe", tarfile.REGTYPE)])
    with pytest.raises(ValueError):
        builder.extract_runtime(source, tmp_path / "destination")
    assert not (tmp_path / "outside").exists()


def test_runtime_extraction_rejects_links_and_case_collisions(tmp_path):
    linked = archive(tmp_path, [("python/lib", b"", tarfile.SYMTYPE)])
    with pytest.raises(ValueError, match="link"):
        builder.extract_runtime(linked, tmp_path / "linked")
    collision = archive(tmp_path, [("python/A", b"one", tarfile.REGTYPE), ("python/a", b"two", tarfile.REGTYPE)])
    with pytest.raises(ValueError, match="collision"):
        builder.extract_runtime(collision, tmp_path / "collision")


def test_runtime_extraction_preserves_notices_but_omits_build_tools(tmp_path):
    source = archive(tmp_path, [
        ("python/LICENSE.txt", b"required notices", tarfile.REGTYPE),
        ("python/python.exe", b"runtime", tarfile.REGTYPE),
        ("python/Lib/site-packages/pip/__init__.py", b"build tool", tarfile.REGTYPE),
        ("python/Scripts/pip.exe", b"absolute launcher", tarfile.REGTYPE),
    ])
    destination = tmp_path / "destination"
    builder.extract_runtime(source, destination)
    assert (destination / "LICENSE.txt").read_bytes() == b"required notices"
    assert not (destination / "Scripts").exists()
    assert not (destination / "Lib/site-packages").exists()


def test_runtime_archive_hash_is_required_for_local_reuse(tmp_path):
    source = tmp_path / "already-downloaded.tar.gz"
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        builder.download_runtime({"sha256": "0" * 64}, tmp_path, source)


def test_runtime_dependency_notices_match_recorded_upstream_bytes():
    directory = RESOURCES / "THIRD-PARTY-RUNTIME-NOTICES"
    sources = json.loads((directory / "sources.json").read_text("utf-8-sig"))
    assert any(item["name"] == "LICENSE.openssl-3.txt" for item in sources)
    for item in sources:
        assert builder.sha256(directory / item["name"]) == item["sha256"]
        assert "/4bb01f09aaf362c71e891be4a41cb6d6ddf830b3/" in item["url"]


def test_builder_omits_absolute_generated_scripts_and_corrects_installed_record(tmp_path):
    site = tmp_path / "site-packages"
    metadata = site / "example-1.dist-info"
    metadata.mkdir(parents=True)
    (site / "bin").mkdir()
    (site / "bin/example.exe").write_bytes(b"absolute builder executable path")
    (site / "example.py").write_text("value = 1", encoding="utf-8")
    (metadata / "direct_url.json").write_text('{"url":"file:///private/build"}', encoding="utf-8")
    record = metadata / "RECORD"
    record.write_text("example.py,,\nbin/example.exe,,\nexample-1.dist-info/direct_url.json,,\nexample-1.dist-info/RECORD,,\n", encoding="utf-8")
    builder.clean_install_metadata(site)
    assert not (site / "bin").exists()
    assert not (metadata / "direct_url.json").exists()
    assert record.read_text().splitlines() == ["example.py,,", "example-1.dist-info/RECORD,,"]
    with pytest.raises(ValueError, match="outside"):
        builder.remove_owned_tree(tmp_path, site)


def make_bundle(directory, version="0.2.0a1", marker="first"):
    shutil.copytree(RESOURCES, directory)
    (directory / "runtime").mkdir()
    (directory / "runtime/python.exe").write_bytes(b"inert fixture interpreter: " + marker.encode())
    plugin = directory / "plugin"
    (plugin / ".codex-plugin").mkdir(parents=True)
    builder.write_json(plugin / ".codex-plugin/plugin.json", {
        "name": "nmr-companion", "version": version.replace("a", "-alpha."),
        "skills": "./skills/", "mcpServers": "./.mcp.json",
    })
    (plugin / "skills/nmr-workflow").mkdir(parents=True)
    (plugin / "skills/nmr-workflow/SKILL.md").write_text(
        f"---\nname: nmr-workflow\ndescription: Synthetic package fixture.\n---\n{marker}\n",
        encoding="utf-8",
    )
    with (directory / "launchers/Launch.ps1").open("a", encoding="utf-8") as file:
        file.write("\n# release fixture " + marker + "\n")
    builder.create_manifest(directory, {"version": version, "platform": "windows-x64"})
    return directory


def manage(root, action, *, bundle=None, script=None, success=True, extra=()):
    manager = script or (bundle or root) / "Manage-Installation.ps1"
    arguments = [POWERSHELL, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(manager), "-Action", action, "-Root", str(root)]
    if bundle:
        arguments += ["-Bundle", str(bundle)]
    result = subprocess.run(arguments + list(extra), capture_output=True, timeout=40)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if success:
        assert result.returncode == 0, output
    else:
        assert result.returncode != 0, output
    return output


def state(root):
    return json.loads((root / "installation.json").read_text("utf-8-sig"))


@WINDOWS
def test_installer_upgrade_repeat_rollback_uninstall_preserve_user_data(tmp_path):
    first = make_bundle(tmp_path / "download with spaces \u5316\u5b66", marker="first")
    second = make_bundle(tmp_path / "upgrade", "0.2.0a2", "second")
    root = tmp_path / "application path \u5b89\u88c5"
    project = tmp_path / "custom project.nmrproj"
    project.write_bytes(b"precious independent scientific data")
    manage(root, "Install", bundle=first)
    initial = state(root)
    adapter_root = root / "codex-marketplace"
    plugin_root = adapter_root / "plugins/nmr-companion"
    mcp = json.loads((plugin_root / ".mcp.json").read_text("utf-8"))["mcpServers"]["nmr-companion"]
    assert mcp["command"] == POWERSHELL
    assert mcp["args"] == ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(root / "Launch.ps1"), "-Mode", "mcp"]
    catalog = json.loads((adapter_root / ".agents/plugins/marketplace.json").read_text("utf-8"))
    assert catalog["name"] == "nmr-companion-local"
    assert catalog["plugins"][0]["source"]["path"] == "./plugins/nmr-companion"
    for relative, digest in initial["adapter_hashes"].items():
        assert builder.sha256(root / relative) == digest
    original_skill = (plugin_root / "skills/nmr-workflow/SKILL.md").read_bytes()
    launch_hash = builder.sha256(root / "Launch.ps1")
    manage(root, "Install", bundle=first)
    assert state(root) == initial
    manage(root, "Install", bundle=second)
    updated = state(root)
    assert updated["previous"] == initial["active"]
    assert updated["active"] != initial["active"]
    assert len(updated["releases"]) == 2
    assert builder.sha256(root / "Launch.ps1") != launch_hash
    assert (plugin_root / "skills/nmr-workflow/SKILL.md").read_bytes() != original_skill
    manage(root, "Rollback")
    rolled_back = state(root)
    assert rolled_back["active"] == initial["active"]
    assert rolled_back["previous"] == updated["active"]
    assert builder.sha256(root / "Launch.ps1") == launch_hash
    assert (plugin_root / "skills/nmr-workflow/SKILL.md").read_bytes() == original_skill
    manage(root, "Verify")
    (root / "my-notes.txt").write_text("retain unknown files", encoding="utf-8")
    output = manage(root, "Uninstall")
    assert '"default_project_removed":  false' in output
    assert list(path.name for path in root.iterdir()) == ["my-notes.txt"]
    assert project.read_bytes() == b"precious independent scientific data"


@WINDOWS
def test_install_rejects_corrupt_source_without_changing_active_release(tmp_path):
    first = make_bundle(tmp_path / "first")
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    before = (root / "installation.json").read_bytes()
    corrupt = make_bundle(tmp_path / "corrupt", "0.2.0a2")
    (corrupt / "runtime/python.exe").write_bytes(b"corrupt")
    assert "missing or changed" in manage(root, "Install", bundle=corrupt, success=False)
    assert (root / "installation.json").read_bytes() == before


@WINDOWS
def test_removal_rejects_unknown_release_files_before_deleting_anything(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    root = tmp_path / "root"
    manage(root, "Install", bundle=source)
    release = root / "releases" / state(root)["active"]
    (release / "user-data.txt").write_text("preserve", encoding="utf-8")
    assert "Unexpected package file" in manage(root, "Uninstall", success=False)
    assert (release / "runtime/python.exe").exists()
    assert (release / "user-data.txt").read_text() == "preserve"
    assert (root / "installation.json").exists()


@WINDOWS
def test_modified_launcher_and_explicit_data_removal_guard(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    root = tmp_path / "root"
    manage(root, "Install", bundle=source)
    assert "exact default workspace path" in manage(
        root, "Uninstall", success=False,
        extra=("-RemoveDefaultProject", "-ConfirmDefaultProject", str(tmp_path / "custom.nmrproj")),
    )
    original = (root / "Launch.ps1").read_bytes()
    (root / "Launch.ps1").write_bytes(original + b"# user customization")
    assert "launcher changed" in manage(root, "Install", bundle=source, success=False)
    assert (root / "Launch.ps1").read_bytes().endswith(b"# user customization")


@WINDOWS
def test_shared_launcher_lock_blocks_install_and_removal(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    root = tmp_path / "root"
    manage(root, "Install", bundle=source)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(root / ".installation.lock"), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert "launcher or installer is active" in manage(root, "Install", bundle=source, success=False)
        assert "launcher or installer is active" in manage(root, "Uninstall", success=False)
    finally:
        kernel.CloseHandle(handle)
    manage(root, "Verify")


@WINDOWS
def test_modified_plugin_adapter_is_preserved_and_blocks_install_and_removal(tmp_path):
    first = make_bundle(tmp_path / "first")
    second = make_bundle(tmp_path / "second", "0.2.0a2", "second")
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    before = (root / "installation.json").read_bytes()
    mcp = root / "codex-marketplace/plugins/nmr-companion/.mcp.json"
    mcp.write_text('{"user_customization":true}', encoding="utf-8")
    assert "plugin adapter changed; preserved" in manage(root, "Install", bundle=second, success=False)
    assert "plugin adapter changed; preserved" in manage(root, "Uninstall", success=False)
    assert (root / "installation.json").read_bytes() == before
    assert mcp.read_text() == '{"user_customization":true}'


@WINDOWS
def test_unknown_plugin_adapter_files_survive_upgrade_and_uninstall(tmp_path):
    first = make_bundle(tmp_path / "first")
    second = make_bundle(tmp_path / "second", "0.2.0a2", "second")
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    unknown = root / "codex-marketplace/plugins/nmr-companion/user-note.txt"
    unknown.write_text("user-owned", encoding="utf-8")
    manage(root, "Install", bundle=second)
    manage(root, "Uninstall")
    assert unknown.read_text() == "user-owned"
    assert not (root / "installation.json").exists()
    assert not (unknown.parent / ".mcp.json").exists()


@WINDOWS
def test_upgrade_does_not_adopt_or_overwrite_an_unowned_adapter_path(tmp_path):
    first = make_bundle(tmp_path / "first")
    second = make_bundle(tmp_path / "second", "0.2.0a2", "second")
    (second / "plugin/skills/nmr-workflow/recipe.txt").write_text("new release resource")
    builder.create_manifest(second, {"version": "0.2.0a2", "platform": "windows-x64"})
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    before = state(root)
    unknown = root / "codex-marketplace/plugins/nmr-companion/skills/nmr-workflow/recipe.txt"
    unknown.write_text("personal recipe", encoding="utf-8")
    assert "Unowned plugin adapter path" in manage(root, "Install", bundle=second, success=False)
    assert state(root) == before
    assert len(list((root / "releases").iterdir())) == 1
    assert unknown.read_text() == "personal recipe"


@WINDOWS
def test_recovery_finishes_recorded_activation_without_scientific_replay(tmp_path):
    first = make_bundle(tmp_path / "first")
    second = make_bundle(tmp_path / "second", "0.2.0a2", "second")
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    prior = (root / "installation.json").read_bytes()
    manage(root, "Install", bundle=second)
    target = (root / "installation.json").read_bytes()
    (root / "pending.json").write_bytes(target)
    (root / "installation.json").write_bytes(prior)
    assert "interrupted" in manage(root, "Verify", success=False)
    manage(root, "Recover")
    assert state(root)["active"] == json.loads(target)["active"]
    assert not (root / "pending.json").exists()
    manage(root, "Verify")


@WINDOWS
def test_recovery_reconciles_partially_written_and_retired_adapter_files(tmp_path):
    first = make_bundle(tmp_path / "first")
    second = make_bundle(tmp_path / "second", "0.2.0a2", "second")
    (first / "plugin/skills/nmr-workflow/obsolete.txt").write_text("old owned resource")
    (second / "plugin/skills/nmr-workflow/recipe.txt").write_text("new owned resource")
    builder.create_manifest(first, {"version": "0.2.0a1", "platform": "windows-x64"})
    builder.create_manifest(second, {"version": "0.2.0a2", "platform": "windows-x64"})
    root = tmp_path / "root"
    manage(root, "Install", bundle=first)
    prior = (root / "installation.json").read_bytes()
    manage(root, "Install", bundle=second)
    target = (root / "installation.json").read_bytes()
    skills = root / "codex-marketplace/plugins/nmr-companion/skills/nmr-workflow"
    assert not (skills / "obsolete.txt").exists()
    (skills / "recipe.txt").rename(skills / "recipe.txt.new")
    (skills / "SKILL.md").write_bytes((first / "plugin/skills/nmr-workflow/SKILL.md").read_bytes())
    (root / "pending.json").write_bytes(target)
    (root / "installation.json").write_bytes(prior)
    manage(root, "Recover")
    manage(root, "Verify")
    assert (skills / "recipe.txt").read_text() == "new owned resource"
    assert not (skills / "recipe.txt.new").exists()
    assert not (skills / "obsolete.txt").exists()
    assert (skills / "SKILL.md").read_bytes() == (second / "plugin/skills/nmr-workflow/SKILL.md").read_bytes()


@WINDOWS
def test_reinstall_rebinds_a_moved_installation_without_changing_projects(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    original = tmp_path / "original root"
    moved = tmp_path / "moved root"
    manage(original, "Install", bundle=source)
    original.rename(moved)
    assert "binding differs" in manage(moved, "Verify", success=False)
    manage(moved, "Install", bundle=source)
    manage(moved, "Verify")
    mcp = json.loads((moved / "codex-marketplace/plugins/nmr-companion/.mcp.json").read_text("utf-8"))
    assert str(moved / "Launch.ps1") in mcp["mcpServers"]["nmr-companion"]["args"]
    assert len(state(moved)["releases"]) == 1


@WINDOWS
def test_installer_rejects_existing_unowned_root_and_manifest_traversal(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    root = tmp_path / "unowned"
    root.mkdir()
    sentinel = root / "unrelated.txt"
    sentinel.write_text("keep")
    assert "empty product directory" in manage(root, "Install", bundle=source, success=False)
    assert sentinel.read_text() == "keep"
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["files"]["../../unrelated.txt"] = {"size": 4, "sha256": "0" * 64}
    builder.write_json(source / "manifest.json", manifest)
    assert "Unsafe package-relative path" in manage(tmp_path / "fresh", "Install", bundle=source, success=False)
    assert not (tmp_path / "fresh").exists()


@WINDOWS
def test_installer_refuses_junction_root_without_touching_its_target(tmp_path):
    source = make_bundle(tmp_path / "bundle")
    target = tmp_path / "unrelated directory"
    target.mkdir()
    sentinel = target / "precious.txt"
    sentinel.write_text("keep", encoding="utf-8")
    junction = tmp_path / "junction root"
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    command = f"New-Item -ItemType Junction -Path {quote(junction)} -Target {quote(target)} | Out-Null"
    result = subprocess.run([POWERSHELL, "-NoProfile", "-Command", command], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    try:
        assert "Reparse points" in manage(junction, "Install", bundle=source, success=False)
        assert sentinel.read_text() == "keep"
        assert list(target.iterdir()) == [sentinel]
    finally:
        # Remove the directory entry only; never traverse/delete the target.
        os.rmdir(junction)

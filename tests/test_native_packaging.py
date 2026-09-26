"""Native launcher processes and installer compatibility in isolated temp roots."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

import pytest

from test_packaging import RESOURCES, ROOT, WINDOWS, builder, make_bundle, manage, state


def minimal_native_site(directory):
    catalog = json.loads((RESOURCES / "THIRD-PARTY-NATIVE-NOTICES/sources.json").read_text())
    for package, version in (("pyside6_essentials", catalog["qt_version"]),
                             ("shiboken6", catalog["qt_version"]),
                             ("pyqtgraph", catalog["pyqtgraph_version"])):
        metadata = directory / f"{package}-{version}.dist-info"
        (metadata / "licenses").mkdir(parents=True)
        (metadata / "METADATA").write_text(f"Name: {package}\nVersion: {version}\n", encoding="ascii")
        (metadata / "licenses/LICENSE.txt").write_text("fixture license", encoding="ascii")
    for relative in ("PySide6/Qt6Core.dll", "PySide6/Qt6Gui.dll", "PySide6/Qt6Widgets.dll",
                     "PySide6/QtCore.pyd", "PySide6/QtGui.pyd", "PySide6/QtWidgets.pyd",
                     "PySide6/plugins/platforms/qwindows.dll", "PySide6/plugins/platforms/qoffscreen.dll",
                     "PySide6/pyside6.abi3.dll", "shiboken6/shiboken6.abi3.dll"):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture shared library")
    return directory


def test_native_payload_requires_windows_platform_and_matching_dependency_notices(tmp_path):
    site = minimal_native_site(tmp_path / "site")
    notices = RESOURCES / "THIRD-PARTY-NATIVE-NOTICES"
    result = builder.validate_native_payload(site, notices)
    assert result["webengine"] is False
    windows_platform = site / "PySide6/plugins/platforms/qwindows.dll"
    original = windows_platform.read_bytes()
    windows_platform.unlink()
    with pytest.raises(ValueError, match="qwindows.dll"):
        builder.validate_native_payload(site, notices)
    windows_platform.write_bytes(original)
    metadata = next(site.glob("shiboken6-*.dist-info/METADATA"))
    metadata.write_text("Name: shiboken6\nVersion: 0.0.0\n", encoding="ascii")
    with pytest.raises(ValueError, match="versions disagree"):
        builder.validate_native_payload(site, notices)


def test_native_payload_omits_browser_only_artifacts_and_rejects_browser_runtime(tmp_path):
    site = minimal_native_site(tmp_path / "site")
    designer = site / "PySide6/plugins/designer/qwebengineview.dll"
    designer.parent.mkdir()
    designer.write_bytes(b"unused upstream Designer plugin")
    stub = site / "PySide6/QtWebEngineCore.pyi"
    stub.write_text("unused upstream type stub", encoding="ascii")
    builder.prune_native_browser_artifacts(site)
    assert not designer.exists() and not stub.exists()
    builder.validate_native_payload(site, RESOURCES / "THIRD-PARTY-NATIVE-NOTICES")
    (site / "PySide6/Qt6WebEngineCore.dll").write_bytes(b"forbidden browser")
    with pytest.raises(ValueError, match="WebEngine"):
        builder.validate_native_payload(site, RESOURCES / "THIRD-PARTY-NATIVE-NOTICES")


def test_all_native_notices_match_pinned_upstream_bytes():
    directory = RESOURCES / "THIRD-PARTY-NATIVE-NOTICES"
    catalog = json.loads((directory / "sources.json").read_text("utf-8"))
    referenced = set()
    for source in catalog["sources"]:
        assert len(source["commit"]) == 40
        assert source["commit"] in source["source_archive"]
        for entry in source["files"]:
            assert source["commit"] in entry["url"]
            assert builder.sha256(directory / entry["file"]) == entry["sha256"]
            referenced.add(entry["file"])
    actual = {path.relative_to(directory).as_posix() for folder in ("licenses", "attributions")
              for path in (directory / folder).iterdir() if path.is_file()}
    assert actual == referenced
    auxiliary = json.loads((directory / "auxiliary-sources.json").read_text("utf-8"))
    assert {entry["name"] for entry in auxiliary["sources"]} == {"Mesa", "LLVM"}
    for entry in auxiliary["sources"]:
        assert builder.sha256(directory / entry["file"]) == entry["sha256"]


def test_every_shipped_qt_library_requires_reviewed_source_mapping(tmp_path):
    site = minimal_native_site(tmp_path / "site")
    expected = {"Qt6Designer.dll": "qt/qttools", "Qt6Lottie.dll": "qt/qtlottie",
                "Qt6QuickTimeline.dll": "qt/qtquicktimeline",
                "Qt6QuickVectorImage.dll": "qt/qtdeclarative"}
    nested = site / "PySide6/nested"
    nested.mkdir()
    for name in expected:
        (nested / name).write_bytes(b"additional shipped Qt library")
    notices = RESOURCES / "THIRD-PARTY-NATIVE-NOTICES"
    result = builder.validate_native_payload(site, notices)
    inventory = {Path(item["path"]).name: item["repository"] for item in result["qt_libraries"]}
    assert expected.items() <= inventory.items()
    assert len(inventory) == 7
    (nested / "Qt6ShaderTools.dll").write_bytes(b"new unreviewed dependency")
    with pytest.raises(ValueError, match="Missing reviewed Qt source mapping:.*Qt6ShaderTools.dll"):
        builder.validate_native_payload(site, notices)


def test_qt_library_mapping_rejects_missing_pinned_source_module(tmp_path):
    site = minimal_native_site(tmp_path / "site")
    (site / "PySide6/Qt6QuickTimeline.dll").write_bytes(b"ancillary module")
    original = RESOURCES / "THIRD-PARTY-NATIVE-NOTICES"
    notices = tmp_path / "notices"
    notices.mkdir()
    shutil.copy2(original / "qt-library-sources.json", notices)
    catalog = json.loads((original / "sources.json").read_text("utf-8"))
    catalog["sources"] = [source for source in catalog["sources"]
                          if source["repository"] != "qt/qtquicktimeline"]
    builder.write_json(notices / "sources.json", catalog)
    with pytest.raises(ValueError, match="Missing pinned Qt source notices: qt/qtquicktimeline"):
        builder.qt_library_sources(site, notices)


@pytest.fixture(scope="module")
def native_binaries(tmp_path_factory):
    if os.name != "nt":
        pytest.skip("Actual Windows native launcher")
    directory = tmp_path_factory.mktemp("native-launcher-compiler")
    launcher = directory / "NMR Companion.exe"
    evidence = builder.compile_native_launcher(ROOT / "packaging/windows/NativeLauncher.cs", launcher)
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    harness_source = directory / "Harness.cs"
    harness_source.write_text(r'''
using System;
using System.Linq;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
public class Harness {
    [DllImport("shell32.dll", SetLastError = true)]
    static extern IntPtr CommandLineToArgvW([MarshalAs(UnmanagedType.LPWStr)] string line, out int count);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr memory);
    static string[] Parse(string line) {
        int count;
        IntPtr memory = CommandLineToArgvW(line, out count);
        try {
            string[] values = new string[count];
            for (int i=0; i<count; i++) values[i] = Marshal.PtrToStringUni(Marshal.ReadIntPtr(memory, i*IntPtr.Size));
            return values;
        } finally { LocalFree(memory); }
    }
    public static int Main(string[] arguments) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        JavaScriptSerializer json = new JavaScriptSerializer();
        if (arguments[0] == "quote") {
            string line = "fixture.exe " + String.Join(" ", arguments.Skip(1).Select(NativeLauncher.QuoteArgument));
            Console.WriteLine(json.Serialize(Parse(line).Skip(1).ToArray()));
            return 0;
        }
        if (arguments[0] == "info") {
            var info = NativeLauncher.StartInfo(arguments[1], arguments.Skip(2).ToArray());
            Console.WriteLine(json.Serialize(new {file=info.FileName, args=Parse("fixture.exe " + info.Arguments).Skip(1).ToArray(),
                shell=info.UseShellExecute, hidden=info.CreateNoWindow, style=info.WindowStyle.ToString()}));
            return 0;
        }
        return NativeLauncher.Run(arguments[1], arguments.Skip(2).ToArray(), Console.Error.WriteLine);
    }
}
''', encoding="utf-8")
    harness = directory / "Harness.exe"
    builder.run([compiler, "/nologo", "/target:exe", "/platform:x64", "/debug-",
                 "/reference:System.Web.Extensions.dll", f"/reference:{launcher}",
                 f"/out:{harness}", harness_source], cwd=directory)
    runtime_source = directory / "RuntimeProbe.cs"
    runtime_source.write_text(r'''
using System;
using System.IO;
using System.Threading;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
public class RuntimeProbe {
    [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
    public static int Main(string[] arguments) {
        string result = Environment.GetEnvironmentVariable("NMR_TEST_RESULT");
        File.WriteAllText(result, new JavaScriptSerializer().Serialize(new {
            args=arguments, console=GetConsoleWindow().ToInt64()}));
        string gate = Environment.GetEnvironmentVariable("NMR_TEST_GATE");
        for (int i=0; gate != null && !File.Exists(gate) && i<300; i++) Thread.Sleep(50);
        string failure = Environment.GetEnvironmentVariable("NMR_TEST_EXIT");
        if (failure != null) Console.Error.WriteLine("fixture startup failure");
        return failure == null ? 0 : Int32.Parse(failure);
    }
}
''', encoding="utf-8")
    runtime = directory / "RuntimeProbe.exe"
    builder.run([compiler, "/nologo", "/target:exe", "/platform:x64", "/debug-",
                 "/reference:System.Web.Extensions.dll", f"/out:{runtime}", runtime_source], cwd=directory)
    return launcher, harness, runtime, evidence


def native_bundle(directory, binaries):
    bundle = make_bundle(directory, version="0.2.0a2", marker="native")
    shutil.copy2(binaries[0], bundle / "launchers/NMR Companion.exe")
    shutil.copy2(binaries[2], bundle / "runtime/python.exe")
    builder.create_manifest(bundle, {"version": "0.2.0a2", "platform": "windows-x64",
                                     "desktop_frontend": "qt-widgets"})
    return bundle


def run_harness(binaries, *arguments, environment=None):
    return subprocess.run([str(binaries[1]), *map(str, arguments)], capture_output=True,
                          timeout=25, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)


@WINDOWS
def test_native_executable_has_gui_subsystem_and_quotes_individual_arguments(native_binaries, tmp_path):
    launcher, _, _, evidence = native_binaries
    binary = launcher.read_bytes()
    pe = struct.unpack_from("<I", binary, 0x3c)[0]
    assert binary[pe:pe + 4] == b"PE\0\0"
    assert struct.unpack_from("<H", binary, pe + 24 + 68)[0] == 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI
    assert evidence["sha256"] == builder.sha256(launcher)
    values = ["", "plain", "two words", "\u5316\u5b66", 'embedded"quote', "trailing\\", 'slash\\"quote',
              "$(Write-Output injected); & 'literal'", "C:\\folder with spaces\\"]
    result = run_harness(native_binaries, "quote", *values)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == values
    project = tmp_path / "selected & literal \u5316\u5b66.nmrproj"
    result = run_harness(native_binaries, "info", tmp_path, "--project", project)
    info = json.loads(result.stdout)
    assert info["shell"] is False and info["hidden"] is True and info["style"] == "Hidden"
    assert info["args"][-4:] == ["-Mode", "desktop", "-Project", str(project)]
    assert "-Command" not in info["args"]


@WINDOWS
def test_native_launcher_waits_without_console_and_preserves_installation_lock(native_binaries, tmp_path):
    bundle = native_bundle(tmp_path / "bundle", native_binaries)
    root = tmp_path / "native application \u5316\u5b66"
    manage(root, "Install", bundle=bundle)
    result_path, gate = tmp_path / "runtime-result.json", tmp_path / "release-gate"
    project = tmp_path / "selected & literal \u5316\u5b66.nmrproj"
    environment = {**os.environ, "NMR_TEST_RESULT": str(result_path), "NMR_TEST_GATE": str(gate)}
    process = subprocess.Popen([str(native_binaries[1]), "run", str(root), "--project", str(project)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 20
        while not result_path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert result_path.exists()
        assert process.poll() is None
        assert "launcher or installer is active" in manage(root, "Uninstall", success=False)
    finally:
        gate.write_text("close synthetic runtime", encoding="ascii")
        output, errors = process.communicate(timeout=20)
    assert process.returncode == 0, output + errors
    probe = json.loads(result_path.read_text())
    assert probe["console"] == 0
    assert probe["args"] == ["-I", "-B", "-m", "nmr_companion", "--project", str(project), "desktop"]
    manage(root, "Verify")
    failure = run_harness(native_binaries, "run", root,
                          environment={**os.environ, "NMR_TEST_RESULT": str(result_path), "NMR_TEST_EXIT": "7"})
    assert failure.returncode == 1
    assert b"NMR Companion could not open" in failure.stderr
    assert b"code 7" in failure.stderr and b"fixture startup failure" in failure.stderr


@WINDOWS
def test_native_manager_migrates_legacy_state_and_survives_rollback_recovery(native_binaries, tmp_path):
    legacy = make_bundle(tmp_path / "legacy")
    native = native_bundle(tmp_path / "native", native_binaries)
    root = tmp_path / "installation"
    manage(root, "Install", bundle=legacy)
    old = state(root)
    old.pop("manager")  # Original alpha.1 state has no manager provenance field.
    builder.write_json(root / "installation.json", old)
    manage(root, "Install", bundle=native)
    current = state(root)
    exe_hash = builder.sha256(root / "NMR Companion.exe")
    assert current["launcher_hashes"]["NMR Companion.exe"] == exe_hash
    assert current["manager"]["release"] == current["active"]
    assert current["manager"]["script_sha256"] == builder.sha256(root / "Manage-Installation.ps1")
    manage(root, "Rollback")
    rolled_back = state(root)
    assert rolled_back["active"] == old["active"]
    assert rolled_back["manager"] == current["manager"]
    assert builder.sha256(root / "NMR Companion.exe") == exe_hash
    manage(root, "Verify")
    unavailable = run_harness(native_binaries, "run", root)
    assert unavailable.returncode == 1
    assert b"does not include the native Windows workbench" in unavailable.stderr
    manage(root, "Rollback")  # The retained manager supports returning to the native release.
    manage(root, "Verify")
    assert state(root)["active"] == current["active"]
    builder.write_json(root / "pending.json", state(root))
    builder.write_json(root / "installation.json", rolled_back)
    manage(root, "Recover")
    manage(root, "Verify")
    assert state(root)["manager"] == current["manager"]
    manage(root, "Uninstall")
    assert not root.exists()


@WINDOWS
def test_installing_legacy_bundle_keeps_native_manager_and_allows_return(native_binaries, tmp_path):
    legacy = make_bundle(tmp_path / "legacy")
    manager = legacy / "Manage-Installation.ps1"
    source = manager.read_text("utf-8-sig")
    native_inventory = "$EntryPoints = @($LegacyEntryPoints) + @('NMR Companion.exe')"
    assert source.count(native_inventory) == 1
    # Model alpha.1's eight-entrypoint parser, which cannot verify native releases.
    manager.write_text(source.replace(native_inventory, "$EntryPoints = @($LegacyEntryPoints)"),
                       encoding="utf-8-sig")
    builder.create_manifest(legacy, {"version": "0.2.0a1", "platform": "windows-x64"})
    native = native_bundle(tmp_path / "native", native_binaries)
    root = tmp_path / "installation"
    manage(root, "Install", bundle=legacy)
    initial = state(root)
    manage(root, "Install", bundle=native)
    current = state(root)
    manager_hash = builder.sha256(root / "Manage-Installation.ps1")
    executable_hash = builder.sha256(root / "NMR Companion.exe")
    assert manager_hash != builder.sha256(manager)
    manage(root, "Install", bundle=legacy, script=root / "Manage-Installation.ps1")
    old_runtime = state(root)
    assert old_runtime["active"] == initial["active"]
    assert old_runtime["previous"] == current["active"]
    assert old_runtime["manager"] == current["manager"]
    assert len(old_runtime["releases"]) == 2
    assert builder.sha256(root / "Manage-Installation.ps1") == manager_hash
    assert builder.sha256(root / "NMR Companion.exe") == executable_hash
    manage(root, "Verify")
    manage(root, "Rollback")
    manage(root, "Verify")
    assert state(root)["active"] == current["active"]
    manage(root, "Uninstall")
    assert not root.exists()


@WINDOWS
def test_native_upgrade_preserves_unowned_executable_before_copying_release(native_binaries, tmp_path):
    legacy = make_bundle(tmp_path / "legacy")
    native = native_bundle(tmp_path / "native", native_binaries)
    root = tmp_path / "installation"
    manage(root, "Install", bundle=legacy)
    before = state(root)
    executable = root / "NMR Companion.exe"
    executable.write_bytes(b"unrelated user file")
    assert "Unowned or modified entrypoint" in manage(root, "Install", bundle=native, success=False)
    assert executable.read_bytes() == b"unrelated user file"
    assert state(root) == before
    assert len(list((root / "releases").iterdir())) == 1

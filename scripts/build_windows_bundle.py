"""Build a relocatable Windows package from a verified runtime and uv.lock.

Maintainer command only: package users do not need Git, uv or Python installed.
The reviewed runtime pin is independent of the product dependency lock.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
import urllib.request
import uuid
import zipfile

REPOSITORY = Path(__file__).resolve().parents[1]
PRODUCT = "nmr-companion"
PRUNED_RUNTIME = (
    "include", "libs", "Scripts", "Lib/site-packages", "Lib/ensurepip",
    "Lib/test", "Lib/idlelib",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value or "\\" in value or ":" in value or path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(part.rstrip(" .") != part for part in path.parts)
        or any(re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I)
               for part in path.parts)
    ):
        raise ValueError(f"Unsafe package path: {value!r}")
    return path


def extract_runtime(archive: Path, destination: Path) -> None:
    """Extract regular files only, with bounds and Windows path collision checks."""
    seen: set[str] = set()
    total = 0
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > 30000:
            raise ValueError("Runtime archive has too many members")
        for member in members:
            path = safe_relative(member.name.rstrip("/"))
            if path.parts[0] != "python":
                raise ValueError("Expected the python/ runtime archive root")
            if not (member.isdir() or member.isfile()):
                raise ValueError("Runtime archive contains a link or special file")
            if len(path.parts) == 1:
                if not member.isdir():
                    raise ValueError("Invalid runtime archive root")
                continue
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative.casefold() in seen:
                raise ValueError("Runtime archive contains a path collision")
            seen.add(relative.casefold())
            total += member.size
            if member.size > 128 * 1024 * 1024 or total > 768 * 1024 * 1024:
                raise ValueError("Runtime archive exceeds extraction limits")
            if any(relative == item or relative.startswith(item + "/")
                   for item in PRUNED_RUNTIME):
                continue
            target = destination.joinpath(*path.parts[1:])
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer)


def download_runtime(pin: dict, cache: Path, provided: Path | None = None) -> Path:
    destination = provided or cache / f"python-{pin['version']}-{pin['build']}.tar.gz"
    if not destination.exists():
        if provided:
            raise FileNotFoundError(provided)
        cache.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(f".{uuid.uuid4().hex}.partial")
        request = urllib.request.Request(pin["url"], headers={"User-Agent": "NMR-Companion-build"})
        try:
            with urllib.request.urlopen(request, timeout=60) as source, partial.open("xb") as out:
                shutil.copyfileobj(source, out)
            if sha256(partial) != pin["sha256"]:
                raise ValueError("Runtime SHA-256 does not match its reviewed pin")
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
    if sha256(destination) != pin["sha256"]:
        raise ValueError("Runtime SHA-256 does not match its reviewed pin")
    return destination


def run(arguments: list[str | Path], *, cwd: Path, timeout: int = 300,
        environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [str(value) for value in arguments], cwd=cwd, text=True,
        encoding="utf-8", capture_output=True, timeout=timeout,
        env={**os.environ, "UV_LINK_MODE": "copy", "PYTHONDONTWRITEBYTECODE": "1",
             **(environment or {})},
    )
    if result.returncode:
        raise RuntimeError(
            f"Build command failed ({result.returncode}): {arguments[0]}\n"
            f"{result.stdout[-6000:]}{result.stderr[-6000:]}"
        )
    return result.stdout.strip()


def inventory(directory: Path) -> dict[str, dict]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Bundle must not contain reparse points")
        if path.is_file() and path != directory / "manifest.json":
            relative = path.relative_to(directory).as_posix()
            safe_relative(relative)
            result[relative] = {"size": path.stat().st_size, "sha256": sha256(path)}
    return result


def create_manifest(directory: Path, metadata: dict) -> dict:
    files = inventory(directory)
    launchers = {
        path.name: path.relative_to(directory).as_posix()
        for path in sorted((directory / "launchers").iterdir()) if path.is_file()
    }
    launchers["Manage-Installation.ps1"] = "Manage-Installation.ps1"
    manifest = {
        "schema_version": 1, "product": PRODUCT, **metadata,
        "launchers": launchers, "files": files,
        "uncompressed_bytes": sum(item["size"] for item in files.values()),
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def git_evidence(repository: Path) -> dict:
    return {
        "commit": run(["git", "rev-parse", "HEAD"], cwd=repository),
        "dirty": bool(run(["git", "status", "--porcelain"], cwd=repository)),
        "uv_lock_sha256": sha256(repository / "uv.lock"),
        "pyproject_sha256": sha256(repository / "pyproject.toml"),
    }


def build_input_hashes(repository: Path) -> dict[str, str]:
    """Detect edits during a build without publishing any maintainer paths."""
    paths = [repository / name for name in ("pyproject.toml", "uv.lock", "LICENSE", "README.md",
             "docs/INSTALLATION.md", "scripts/build_windows_bundle.py", ".codex-plugin/plugin.json")]
    for relative in ("src/nmr_companion", "packaging/windows", "skills"):
        paths.extend(path for path in (repository / relative).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    return {path.relative_to(repository).as_posix(): sha256(path) for path in sorted(paths)}


def assert_tracked_inputs(repository: Path, inputs: dict[str, str]) -> None:
    """Git cleanliness excludes ignored files; every build input must be tracked."""
    tracked = set(run(["git", "ls-files", "--cached", "-z"], cwd=repository).split("\0"))
    missing = sorted(set(inputs) - tracked)
    if missing:
        raise ValueError("Untracked build inputs are not allowed: " + ", ".join(missing))


def remove_owned_tree(path: Path, owner: Path) -> None:
    resolved = path.resolve()
    if resolved == owner.resolve() or not resolved.is_relative_to(owner.resolve()):
        raise ValueError("Refusing to remove a path outside the build-owned tree")
    if path.is_symlink() or path.is_junction():
        raise ValueError("Refusing to remove a linked build directory")
    shutil.rmtree(path)


def clean_install_metadata(site: Path) -> None:
    """Omit unused absolute script launchers and local wheel-origin metadata."""
    for scripts in (site / "bin", site / "Scripts"):
        if scripts.exists():
            remove_owned_tree(scripts, site)
    for path in site.rglob("direct_url.json"):
        path.unlink()
    for record in site.glob("*.dist-info/RECORD"):
        with record.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.reader(stream))
        retained = []
        for row in rows:
            target = (site / row[0]).resolve()
            if target.is_relative_to(site.resolve()) and target.is_file():
                retained.append(row)
        with record.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(retained)


def build(args: argparse.Namespace) -> Path:
    if os.name != "nt":
        raise RuntimeError("Build and smoke-test the Windows bundle on Windows x64")
    repository = args.repository.resolve()
    resources = repository / "packaging" / "windows"
    version = tomllib.loads((repository / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", version):
        raise ValueError("Product version is not a safe release identifier")
    pin = json.loads((resources / "python-runtime.json").read_text("utf-8"))
    inputs = build_input_hashes(repository)
    assert_tracked_inputs(repository, inputs)
    source = git_evidence(repository)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f"nmr-companion-{version}-windows-x64"
    destination = output / f"{name}.zip"
    if destination.exists():
        raise FileExistsError(f"Refusing to replace an existing package: {destination}")
    archive = download_runtime(pin, output / "cache", args.python_archive)
    with tempfile.TemporaryDirectory(prefix="nmr-build-", dir=output) as temporary:
        working = Path(temporary)
        bundle = working / name
        bundle.mkdir()
        runtime = bundle / "runtime"
        extract_runtime(archive, runtime)
        (runtime / "python312._pth").write_text(
            "Lib\nDLLs\nLib/site-packages\n.\nimport site\n", encoding="ascii"
        )
        python = runtime / "python.exe"
        runtime_version = run([python, "-I", "-B", "-c", "import platform; print(platform.python_version())"], cwd=working)
        if runtime_version != pin["version"]:
            raise ValueError("Extracted runtime version does not match the reviewed pin")
        requirements = bundle / "requirements.lock.txt"
        run([args.uv, "export", "--locked", "--no-dev", "--no-emit-project", "--no-header",
             "--format", "requirements-txt", "--output-file", requirements], cwd=repository)
        site = runtime / "Lib" / "site-packages"
        run([args.uv, "pip", "install", "--python", python, "--target", site,
             "--require-hashes", "--only-binary", ":all:", "--no-deps",
             "--link-mode", "copy", "-r", requirements], cwd=working)
        wheels = working / "wheels"
        run([args.uv, "build", "--wheel", "--out-dir", wheels], cwd=repository)
        wheel_list = list(wheels.glob("nmr_companion-*.whl"))
        if len(wheel_list) != 1:
            raise ValueError("Expected exactly one product wheel")
        wheel = wheel_list[0]
        run([args.uv, "pip", "install", "--python", python, "--target", site,
             "--no-deps", "--no-build", "--link-mode", "copy", wheel], cwd=working)
        for path in runtime.rglob("__pycache__"):
            remove_owned_tree(path, runtime)
        clean_install_metadata(site)
        metadata_code = (
            "import importlib.metadata as m,json,platform,nmr_companion; "
            "print(json.dumps({'python':platform.python_version(),"
            "'product':m.version('nmr-companion'),'source_version':nmr_companion.__version__,"
            "'dependencies':sorted([{'name':d.metadata['Name'],'version':d.version} "
            "for d in m.distributions()],key=lambda x:x['name'].lower())}))"
        )
        installed = json.loads(run([python, "-I", "-B", "-c", metadata_code], cwd=working))
        if installed["product"] != version or installed["source_version"] != version:
            raise ValueError("Wheel metadata, source and pyproject versions disagree")
        plugin_metadata = json.loads((repository / ".codex-plugin/plugin.json").read_text("utf-8"))
        plugin_version = re.sub(r"a(\d+)$", r"-alpha.\1", version)
        plugin_version = re.sub(r"b(\d+)$", r"-beta.\1", plugin_version)
        plugin_version = re.sub(r"rc(\d+)$", r"-rc.\1", plugin_version)
        if plugin_metadata["name"] != PRODUCT or plugin_metadata["version"] != plugin_version:
            raise ValueError("Source plugin identity/version disagrees with the product package")
        shutil.copytree(repository / ".codex-plugin", bundle / "plugin" / ".codex-plugin")
        shutil.copytree(repository / "skills", bundle / "plugin" / "skills")
        shutil.copy2(repository / "LICENSE", bundle / "plugin" / "LICENSE")
        for path in (resources / "resources").iterdir():
            if path.is_dir():
                shutil.copytree(path, bundle / path.name)
            else:
                shutil.copy2(path, bundle / path.name)
        shutil.copy2(repository / "LICENSE", bundle / "LICENSE")
        shutil.copy2(repository / "docs" / "INSTALLATION.md", bundle / "INSTALLATION.md")
        shutil.copy2(resources / "python-runtime.json", bundle / "python-runtime.json")
        relocated = working / "relocated path \u5316\u5b66" / name
        relocated.parent.mkdir()
        bundle.rename(relocated)
        bundle = relocated
        python = bundle / "runtime" / "python.exe"
        poison = working / "external Python environment"
        poison.mkdir()
        (poison / "nmr_companion.py").write_text("raise RuntimeError('External import path used')\n", encoding="ascii")
        started = time.perf_counter()
        probe = json.loads(run([python, "-I", "-B", "-c", metadata_code], cwd=output,
                              environment={"PYTHONPATH": str(poison), "PYTHONHOME": str(poison)}))
        import_seconds = round(time.perf_counter() - started, 4)
        if probe != installed:
            raise ValueError("Moved runtime resolved a different package")
        started = time.perf_counter()
        run([python, "-I", "-B", "-m", "nmr_companion", "--help"], cwd=output, timeout=60)
        cli_startup_seconds = round(time.perf_counter() - started, 4)
        started = time.perf_counter()
        self_test = run([python, "-I", "-B", "-m", "nmr_companion", "self-test"], cwd=output, timeout=60)
        self_test_seconds = round(time.perf_counter() - started, 4)
        write_json(bundle / "build-evidence.json", {
            "relocation": "passed-space-and-unicode-path", "import_seconds": import_seconds,
            "cli_startup_seconds": cli_startup_seconds,
            "self_test_seconds": self_test_seconds, "self_test": self_test,
            "installed": installed,
            "scope": "Package process only; installed host/model, GUI and delivery acceptance are separate.",
        })
        if build_input_hashes(repository) != inputs or git_evidence(repository) != source:
            raise RuntimeError("Build inputs changed during packaging; stop writers and rebuild")
        assert_tracked_inputs(repository, inputs)
        source["build_inputs"] = inputs
        create_manifest(bundle, {
            "version": version, "platform": "windows-x64",
            "built_at": datetime.now(timezone.utc).isoformat(),
            "source": source, "python_runtime": pin,
            "codex_plugin_version": plugin_version,
            "wheel": {"name": wheel.name, "sha256": sha256(wheel)},
            "dependencies": installed["dependencies"],
        })
        temporary_package = working / destination.name
        with zipfile.ZipFile(temporary_package, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as package:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    package.write(path, f"{name}/{path.relative_to(bundle).as_posix()}")
        temporary_package.rename(destination)
    checksum = sha256(destination)
    destination.with_suffix(".zip.sha256").write_text(f"{checksum}  {destination.name}\n", encoding="ascii")
    write_json(destination.with_suffix(".build.json"), {
        "package": destination.name, "sha256": checksum,
        "compressed_bytes": destination.stat().st_size,
        "version": version, "import_seconds": import_seconds,
        "cli_startup_seconds": cli_startup_seconds,
        "self_test_seconds": self_test_seconds,
    })
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=REPOSITORY)
    parser.add_argument("--output", type=Path, default=REPOSITORY / "dist" / "windows")
    parser.add_argument("--python-archive", type=Path, help="Existing archive; reviewed SHA-256 is still required")
    parser.add_argument("--uv", default="uv", help="Maintainer uv executable")
    print(build(parser.parse_args()))


if __name__ == "__main__":
    main()

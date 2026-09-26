"""Maintainer-only refresh of public notices for the locked native dependencies.

Ordinary package builds are offline with respect to this collection. Every saved
file is pinned to an upstream commit, byte-hashed, and subsequently tracked in Git.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import posixpath
import urllib.request

SOURCES = {
    "qt/qtbase": "ef55f427f2c8b410d34f8a7681020a3000cf6866",
    "qt/qtdeclarative": "4e3399c26ec57246c08de019cfcbda8d23604cfa",
    "qt/qttools": "8026c0462f19e9549501718152523ea223a19fd3",
    "qt/qtsvg": "17ca512f903f935282ebeca496aac5d11ba4199a",
    "qt/qtlottie": "2b64c8abf2476eb2278283b54412131c5d444f19",
    "qt/qtquicktimeline": "31aaa7427b4e653f5dd9ceaad1773b1bbd750d74",
    "pyside/pyside-setup": "24627cd36e1593adf22eb1f2950e4248e7bcc1ec",
    "pyqtgraph/pyqtgraph": "a20028b98294b9cc8770f2015a92eb342224b788",
}
ROOT = Path(__file__).parent / "resources/THIRD-PARTY-NATIVE-NOTICES"


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "NMR-Companion-notices"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read()


def collect(repository, commit):
    tree = json.loads(get(f"https://api.github.com/repos/{repository}/git/trees/{commit}?recursive=1"))
    if tree.get("truncated"):
        raise ValueError(f"Incomplete upstream tree: {repository}")
    paths = {item["path"] for item in tree["tree"] if item["type"] == "blob"}
    selected = {path for path in paths if path.startswith("LICENSES/") or
                ("/" not in path and path in {"LICENSE.txt", "LICENSE", "COPYING", "COPYING.txt"})}
    attribution_paths = sorted(path for path in paths if path.endswith("qt_attribution.json")
                               and not path.startswith("tests/"))
    fetched = {}
    for path in attribution_paths:
        raw = get(f"https://raw.githubusercontent.com/{repository}/{commit}/{path}")
        fetched[path] = raw
        # Some upstream copyright strings contain literal newlines. Preserve bytes.
        records = json.loads(raw, strict=False)
        if isinstance(records, dict):
            records = [records]
        for record in records:
            values = record.get("LicenseFile", [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                candidates = [posixpath.normpath(posixpath.join(posixpath.dirname(path), value)), value]
                matches = [candidate for candidate in candidates if candidate in paths]
                if matches:
                    selected.add(matches[0])
    for path in sorted(selected):
        fetched[path] = get(f"https://raw.githubusercontent.com/{repository}/{commit}/{path}")
    files = []
    for path, raw in sorted(fetched.items()):
        digest = hashlib.sha256(raw).hexdigest()
        category, extension = ("attributions", ".json") if path in attribution_paths else ("licenses", ".txt")
        output = ROOT / category / (digest + extension)
        # Several modules share license texts. Never replace different existing bytes.
        if output.exists():
            if output.read_bytes() != raw:
                raise ValueError(f"Existing notice changed: {output.name}")
        else:
            output.write_bytes(raw)
        files.append({"source_path": path,
                      "url": f"https://raw.githubusercontent.com/{repository}/{commit}/{path}",
                      "sha256": digest, "file": output.relative_to(ROOT).as_posix()})
    return {"repository": repository, "ref": "pyqtgraph-0.14.0" if repository.startswith("pyqtgraph/") else "v6.11.2",
            "commit": commit, "source_archive": f"https://github.com/{repository}/archive/{commit}.tar.gz",
            "files": files}


def main():
    for category in ("licenses", "attributions"):
        (ROOT / category).mkdir(parents=True, exist_ok=True)
    results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect, repo, commit): repo for repo, commit in SOURCES.items()}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"Collected {result['repository']}: {len(result['files'])} notices", flush=True)
    results.sort(key=lambda item: item["repository"])
    (ROOT / "sources.json").write_text(json.dumps({"qt_version": "6.11.2", "pyqtgraph_version": "0.14.0",
                                                 "sources": results}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

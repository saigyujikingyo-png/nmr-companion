"""Prevent runtime, protocol and package identities from drifting at release."""
import json
from pathlib import Path
import tomllib

from nmr_companion import __version__
from nmr_companion.mcp_server import make_server
from nmr_companion.service import Service


def test_runtime_protocol_and_package_share_release_identity(tmp_path):
    root = Path(__file__).resolve().parents[1]
    package = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]
    plugin = json.loads((root / ".codex-plugin/plugin.json").read_text("utf-8"))
    assert __version__ == package["version"]
    assert plugin["version"] == __version__.replace("a", "-alpha.")
    initialized = make_server(Service(tmp_path / "unopened.nmrproj")).create_initialization_options()
    assert initialized.server_name == "nmr-companion"
    assert initialized.server_version == __version__
    assert not (tmp_path / "unopened.nmrproj").exists()

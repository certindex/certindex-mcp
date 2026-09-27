"""Keep published, runtime and registry versions in agreement."""

import json
import tomllib
from importlib.metadata import version
from pathlib import Path

from certindex_mcp import __version__
from certindex_mcp.client import USER_AGENT


def test_release_versions_agree():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    registry = json.loads((root / "server.json").read_text())
    assert project["project"]["version"] == __version__
    assert version("certindex-mcp") == __version__
    assert registry["version"] == __version__
    assert registry["packages"][0]["version"] == __version__
    assert USER_AGENT.startswith(f"certindex-mcp/{__version__} ")

"""Unit tests for the manifest version bump helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bump_manifest_version.py"
_spec = importlib.util.spec_from_file_location("bump_manifest_version", _SCRIPT)
bump_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_module)


@pytest.mark.parametrize(
    ("version", "part", "expected"),
    [
        ("1.0.0", "patch", "1.0.1"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
        ("0.9.9", "minor", "0.10.0"),
    ],
)
def test_bump(version: str, part: str, expected: str) -> None:
    """Each part increments and resets lower parts correctly."""
    assert bump_module.bump(version, part) == expected


def test_bump_rejects_unknown_part() -> None:
    """An unknown bump part raises."""
    with pytest.raises(ValueError, match="Unknown bump part"):
        bump_module.bump("1.0.0", "build")


def test_bump_rejects_bad_version() -> None:
    """A non-semver version raises."""
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        bump_module.bump("1.0", "patch")


def test_manifest_path_points_at_integration() -> None:
    """The script targets the real integration manifest."""
    assert bump_module.MANIFEST.name == "manifest.json"
    assert bump_module.MANIFEST.exists()

#!/usr/bin/env python3
"""Bump the semantic version stored in the integration manifest.

The manifest ``version`` is the single source of truth used by HACS. This
script increments it (major/minor/patch), writes it back preserving key order
and indentation, and prints the new version to stdout so CI can capture it.

Usage:
    python scripts/bump_manifest_version.py [major|minor|patch]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "hoymiles_solarpv"
    / "manifest.json"
)

VALID_PARTS = ("major", "minor", "patch")


def bump(version: str, part: str) -> str:
    """Return ``version`` with the requested semver ``part`` incremented."""
    if part not in VALID_PARTS:
        raise ValueError(f"Unknown bump part {part!r}; expected one of {VALID_PARTS}.")
    try:
        major, minor, patch = (int(piece) for piece in version.split("."))
    except ValueError as err:
        raise ValueError(f"Version {version!r} is not in MAJOR.MINOR.PATCH form.") from err
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main(argv: list[str]) -> int:
    """Bump the manifest version in place and print the new version."""
    part = argv[1] if len(argv) > 1 else "patch"
    data = json.loads(MANIFEST.read_text())
    new_version = bump(data["version"], part)
    data["version"] = new_version
    MANIFEST.write_text(json.dumps(data, indent=4) + "\n")
    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Exercise version drift and repair in isolated copies of release metadata."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "changed",
    [
        "crates/pinterest-core/Cargo.toml",
        "crates/pinterest-cli/Cargo.toml",
        "crates/pinterest-browser/Cargo.toml",
        "Cargo.lock",
    ],
)
def test_rust_version_drift_is_rejected_and_repaired(tmp_path, changed):
    files = [
        "scripts/sync_version.py",
        "extension/manifest.json",
        "pyproject.toml",
        "src/_version.py",
        "crates/pinterest-core/Cargo.toml",
        "crates/pinterest-cli/Cargo.toml",
        "crates/pinterest-browser/Cargo.toml",
        "Cargo.lock",
    ]
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    target = tmp_path / changed
    version = json.loads((ROOT / "extension/manifest.json").read_text())["version"]
    target.write_text(target.read_text().replace(f'version = "{version}"', 'version = "9.9.9"'))
    command = [sys.executable, str(tmp_path / "scripts/sync_version.py")]
    result = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "DIVERGENCIA" in result.stdout
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([*command, "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "extension/manifest.json").read_bytes() == (ROOT / "extension/manifest.json").read_bytes()

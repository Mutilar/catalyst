import os
from pathlib import Path

from tools.environments import local
from tools.environments.local import _prepend_current_butler_bin


def test_current_butler_generation_precedes_captured_path(tmp_path):
    package = tmp_path / "run/target/toolchains/butler/current/bin"
    package.mkdir(parents=True)
    (package / "lucid").write_bytes(b"native")
    (package / "butler").write_bytes(b"native")
    captured = os.pathsep.join(["/stale/bin", str(package), "/usr/bin"])

    projected = _prepend_current_butler_bin(
        captured,
        {"BUTLER_REPOSITORY_ROOT": str(tmp_path)},
    )

    assert projected.split(os.pathsep) == [str(package), "/stale/bin", "/usr/bin"]


def test_missing_configured_generation_uses_integrated_repository(tmp_path):
    captured = os.pathsep.join(["/stale/bin", "/usr/bin"])
    integrated = Path(local.__file__).resolve().parents[3] / "run/target/toolchains/butler/current/bin"

    projected = _prepend_current_butler_bin(
        captured,
        {"BUTLER_REPOSITORY_ROOT": str(tmp_path)},
    )

    assert projected.split(os.pathsep)[0] == str(integrated)

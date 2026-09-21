"""Contract tests for the registered quality runner, not quality measurements."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_lint_config import _run_quality_adapter


RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "quality" / "test.mjs"


def python_summary(**overrides):
    counts = dict.fromkeys(
        ("failed", "skipped", "errors", "xfailed", "xpassed", "deselected",
         "file_failures", "unmeasured_files"), 0
    )
    return "HERMES_TEST_SUMMARY " + json.dumps({
        "schema": "hermes-test-summary/1",
        "files": 1,
        "completed": 1,
        "passed": 7,
        **counts,
        **overrides,
    })


@pytest.mark.parametrize(
    ("python", "desktop", "summary", "running"),
    [
        (python_summary(), "Tests 5 passed (5)", "12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;", 12),
        (
            python_summary(skipped=2, xfailed=1, deselected=3),
            "Tests 5 passed | 4 skipped | 2 todo (11)",
            "12 passed; 0 failed; 9 ignored; 0 measured; 3 filtered out;",
            21,
        ),
        (
            python_summary(xpassed=2),
            "Tests 5 passed (5)",
            "14 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;",
            14,
        ),
        ("no summary", "Tests 5 passed (5)", None, None),
        ("HERMES_TEST_SUMMARY {invalid}", "Tests 5 passed (5)", None, None),
        (python_summary(completed=0), "Tests 5 passed (5)", None, None),
        (python_summary(unmeasured_files=1), "Tests 5 passed (5)", None, None),
        (python_summary(failed=1), "Tests 5 passed (5)", None, None),
        (python_summary(passed=-1), "Tests 5 passed (5)", None, None),
        (python_summary(passed=True), "Tests 5 passed (5)", None, None),
        (python_summary(passed=0, skipped=7), "Tests 5 passed (5)", None, None),
    ],
)
def test_registered_summary_preserves_actual_outcomes(
    tmp_path, monkeypatch, python, desktop, summary, running
):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k externally_filtered")
    result = _run_quality_adapter(
        "test", "success", tmp_path, outputs={"python": python, "desktop": desktop}
    )
    if summary is None:
        assert result.returncode == 2
        assert "quality summary unavailable" in result.stderr
        assert "test result: ok." not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert f"running {running} tests\n" in result.stdout
        assert f"test result: ok. {summary}\n" in result.stdout


@pytest.mark.parametrize("unmeasured", [False, True])
def test_native_runner_measures_complete_file_selection(tmp_path, monkeypatch, unmeasured):
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run_tests_parallel.py"
    runner.write_bytes((RUNNER.parents[1] / "run_tests_parallel.py").read_bytes())
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_counts.py").write_text(
        "import pytest\n"
        "def test_pass(): pass\n"
        "@pytest.mark.skip\n"
        "def test_skip(): pass\n"
        "@pytest.mark.xfail\n"
        "def test_xfail(): assert False\n"
        "@pytest.mark.xfail\n"
        "def test_xpass(): pass\n"
        "def test_dropped(): pass\n",
        encoding="utf-8",
    )
    (tests / "example_test.py").write_text("def test_suffix(): pass\n", encoding="utf-8")
    (tests / "test_empty.py").write_text(
        "import os\nos._exit(0)\n" if unmeasured else "",
        encoding="utf-8",
    )
    for name in ("integration", "e2e", "docker"):
        directory = tests / name
        directory.mkdir()
        (directory / "test_selected.py").write_text("def test_selected(): pass\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, str(runner), "--quality-summary", "--include-integration",
            "--file-retries", "0", "--jobs", "2", "--slice", "1/1",
            "tests", "--", "-q", "-k", "not dropped",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == (1 if unmeasured else 0), result.stdout + result.stderr
    records = [
        json.loads(line.removeprefix("HERMES_TEST_SUMMARY "))
        for line in result.stdout.splitlines()
        if line.startswith("HERMES_TEST_SUMMARY ")
    ]
    assert records == [{
        "schema": "hermes-test-summary/1",
        "files": 6, "completed": 6, "file_failures": 0,
        "unmeasured_files": int(unmeasured),
        "passed": 5, "failed": 0, "skipped": 1, "errors": 0,
        "xfailed": 1, "xpassed": 1, "deselected": 1,
    }]

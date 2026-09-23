"""Bounded coverage-adapter contracts; synthetic reports never reach real receipts."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "quality" / "coverage.mjs"


@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("test_exit", [0, 1, 2, None])
@pytest.mark.parametrize("report_exit", [0, 3])
def test_coverage_adapter_preserves_exact_counts_and_full_report(tmp_path, invalid, test_exit, report_exit):
    adapter = tmp_path / "catalyst" / "scripts" / "quality" / "coverage.mjs"
    adapter.parent.mkdir(parents=True)
    adapter.write_bytes(SOURCE.read_bytes())
    (adapter.parent / "command.mjs").write_bytes(SOURCE.with_name("command.mjs").read_bytes())
    report = {
        "meta": {"version": "7.16.1", "branch_coverage": True},
        "totals": {
            "num_statements": 10,
            "covered_lines": 11 if invalid else 7,
            "num_branches": 8,
            "covered_branches": 3,
        },
        "files": {"module.py": {"executed_lines": [1, 2, 3]}},
    }
    preload = tmp_path / "coverage-probe.mjs"
    preload.write_text(
        "import assert from 'node:assert/strict';\n"
        "import childProcess from 'node:child_process';\n"
        "import { writeFileSync } from 'node:fs';\n"
        "import { syncBuiltinESMExports } from 'node:module';\n"
        "import { EventEmitter } from 'node:events';\n"
        "import { PassThrough } from 'node:stream';\n"
        f"const report = {json.dumps(report)};\n"
        f"const testExit = {json.dumps(test_exit)};\n"
        f"const reportExit = {report_exit};\n"
        "const calls = [];\n"
        "childProcess.spawn = (command, args, options) => {\n"
        "  assert.equal(command, 'uv');\n"
        "  assert.ok(args.includes('--frozen') && args.includes('--offline'));\n"
        "  assert.ok(args.includes('coverage==7.16.1'));\n"
        "  assert.equal(options.env.PYTEST_ADDOPTS, '');\n"
        "  assert.ok(options.env.COVERAGE_FILE);\n"
        "  calls.push(args);\n"
        "  if (args.includes('combine')) writeFileSync(options.env.COVERAGE_FILE, 'fixture coverage data');\n"
        "  if (args.includes('json') && reportExit === 0) writeFileSync(args.at(-1), JSON.stringify(report));\n"
        "  const status = calls.length === 1 ? testExit : args.includes('json') ? reportExit : 0;\n"
        "  const child = new EventEmitter();\n"
        "  child.stdout = new PassThrough(); child.stderr = new PassThrough();\n"
        "  queueMicrotask(() => child.emit('close', status, testExit === null ? 'SIGTERM' : null));\n"
        "  return child;\n"
        "};\n"
        "process.on('exit', () => {\n"
        "  assert.equal(calls.length, testExit === null ? 1 : 3);\n"
        "  assert.ok(calls[0].includes('--coverage'));\n"
        "  assert.ok(calls[0].includes('--include-integration'));\n"
        "  assert.equal(calls[0][calls[0].indexOf('--jobs') + 1], '8');\n"
        "  if (testExit !== null) {\n"
        "    assert.ok(calls[1].includes('combine'));\n"
        "    assert.ok(calls[2].includes('json'));\n"
        "  }\n"
        "});\n"
        "syncBuiltinESMExports();\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", "--import", preload.as_uri(), str(adapter), "--check"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if test_exit is None:
        assert result.returncode == 2
        assert "terminated without an exit status" in result.stderr
        assert not (tmp_path / "catalyst" / ".pytest_cache").exists()
        return
    if invalid or report_exit:
        assert result.returncode == (report_exit or 2)
        if not report_exit:
            assert "quality coverage summary unavailable" in result.stderr
        retained = tmp_path / "catalyst" / ".pytest_cache" / "quality-coverage"
        assert len(list(retained.glob("*.coverage"))) == 1
        assert not list(retained.glob("*.json"))
        return

    assert result.returncode == test_exit, result.stderr
    if test_exit:
        assert "retained without qualification" in result.stderr
    summary = json.loads(result.stdout)
    retained_summary = tmp_path / summary["provenance"]["summary"]
    assert json.loads(retained_summary.read_text()) == summary
    assert summary["data"] == [{"totals": {
        "lines": {"count": 10, "covered": 7},
        "branches": {"count": 8, "covered": 3},
    }}]
    retained = tmp_path / summary["provenance"]["report"]
    assert summary["provenance"]["test_exit_code"] == test_exit
    raw_data = tmp_path / summary["provenance"]["data"]
    assert raw_data.read_text() == "fixture coverage data"
    assert summary["provenance"]["data_sha256"] == (
        "sha256:" + hashlib.sha256(raw_data.read_bytes()).hexdigest()
    )
    assert json.loads(retained.read_text()) == report
    assert summary["provenance"]["sha256"] == (
        "sha256:" + hashlib.sha256(retained.read_bytes()).hexdigest()
    )


def test_summarize_existing_report_never_reexecutes_tests(tmp_path):
    adapter = tmp_path / "catalyst" / "scripts" / "quality" / "coverage.mjs"
    adapter.parent.mkdir(parents=True)
    adapter.write_bytes(SOURCE.read_bytes())
    (adapter.parent / "command.mjs").write_bytes(SOURCE.with_name("command.mjs").read_bytes())
    report = tmp_path / "catalyst" / "measured.json"
    report.write_text(json.dumps({
        "meta": {"version": "7.16.1", "branch_coverage": True},
        "totals": {
            "num_statements": 10, "covered_lines": 7,
            "num_branches": 8, "covered_branches": 3,
        },
    }))
    preload = tmp_path / "no-execution.mjs"
    preload.write_text(
        "import childProcess from 'node:child_process';\n"
        "import { syncBuiltinESMExports } from 'node:module';\n"
        "childProcess.spawn = () => { throw new Error('must not execute tests'); };\n"
        "syncBuiltinESMExports();\n"
    )
    result = subprocess.run(
        ["node", "--import", preload.as_uri(), str(adapter), "--summarize", str(report)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["provenance"]["test_exit_code"] is None
    assert summary["data"][0]["totals"]["branches"] == {"count": 8, "covered": 3}
    assert json.loads((tmp_path / summary["provenance"]["summary"]).read_text()) == summary

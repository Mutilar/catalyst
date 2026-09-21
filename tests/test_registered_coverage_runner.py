"""Bounded coverage-adapter contracts; synthetic reports never reach real receipts."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "quality" / "coverage.mjs"


@pytest.mark.parametrize("invalid", [False, True])
def test_coverage_adapter_preserves_exact_counts_and_full_report(tmp_path, invalid):
    adapter = tmp_path / "catalyst" / "scripts" / "quality" / "coverage.mjs"
    adapter.parent.mkdir(parents=True)
    adapter.write_bytes(SOURCE.read_bytes())
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
        f"const report = {json.dumps(report)};\n"
        "const calls = [];\n"
        "childProcess.spawnSync = (command, args, options) => {\n"
        "  assert.equal(command, 'uv');\n"
        "  assert.ok(args.includes('--frozen') && args.includes('--offline'));\n"
        "  assert.ok(args.includes('coverage==7.16.1'));\n"
        "  assert.equal(options.env.PYTEST_ADDOPTS, '');\n"
        "  assert.ok(options.env.COVERAGE_FILE);\n"
        "  calls.push(args);\n"
        "  if (args.includes('json')) writeFileSync(args.at(-1), JSON.stringify(report));\n"
        "  return { status: 0, stdout: '', stderr: '' };\n"
        "};\n"
        "process.on('exit', () => {\n"
        "  assert.equal(calls.length, 3);\n"
        "  assert.ok(calls[0].includes('--coverage'));\n"
        "  assert.ok(calls[0].includes('--include-integration'));\n"
        "  assert.equal(calls[0][calls[0].indexOf('--jobs') + 1], '8');\n"
        "  assert.ok(calls[1].includes('combine'));\n"
        "  assert.ok(calls[2].includes('json'));\n"
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
    if invalid:
        assert result.returncode == 2
        assert "quality coverage summary unavailable" in result.stderr
        assert not (tmp_path / "catalyst" / ".pytest_cache").exists()
        return

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["data"] == [{"totals": {
        "lines": {"count": 10, "covered": 7},
        "branches": {"count": 8, "covered": 3},
    }}]
    retained = tmp_path / summary["provenance"]["report"]
    assert json.loads(retained.read_text()) == report
    assert summary["provenance"]["sha256"] == (
        "sha256:" + hashlib.sha256(retained.read_bytes()).hexdigest()
    )

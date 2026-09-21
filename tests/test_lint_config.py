"""Tests for ruff lint config — guards against accidental rule removal.

PLW1514 (unspecified-encoding) was enabled after a debug session on
Windows turned up three separate UTF-8 regressions in execute_code.
The rule catches bare ``open()`` / ``read_text()`` / ``write_text()``
calls that default to locale encoding — cp1252 on Windows — which
silently corrupts non-ASCII content.

These tests ensure:
  1. PLW1514 stays in ``[tool.ruff.lint.select]``
  2. The CI workflow's blocking step still invokes ``ruff check .``
  3. pyproject.toml has ``preview = true`` (required — PLW1514 is a
     preview rule in ruff 0.15.x)

If someone removes any of these, CI stops enforcing UTF-8-explicit
opens and we're back to the original Windows-regression trap.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover — 3.10 and earlier
    import tomli as tomllib  # type: ignore

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


class TestRuffConfig:
    def test_plw1514_is_in_select_list(self):
        """pyproject.toml must keep PLW1514 in [tool.ruff.lint.select]."""
        cfg = _load_pyproject()
        selected = (
            cfg.get("tool", {})
            .get("ruff", {})
            .get("lint", {})
            .get("select", [])
        )
        assert "PLW1514" in selected, (
            "PLW1514 (unspecified-encoding) was removed from "
            "[tool.ruff.lint.select].  This rule blocks bare open() calls "
            "that default to locale encoding on Windows — removing it "
            "re-opens a class of UTF-8 bugs we already paid to close.  "
            "If you genuinely want to remove it, delete this test in the "
            "same commit so the intent is deliberate."
        )

    def test_preview_mode_enabled(self):
        """PLW1514 is a preview rule in ruff 0.15.x — preview=true is
        required for it to actually run."""
        cfg = _load_pyproject()
        ruff_cfg = cfg.get("tool", {}).get("ruff", {})
        assert ruff_cfg.get("preview") is True, (
            "[tool.ruff] preview=true is required — PLW1514 is a preview "
            "rule and silently becomes a no-op without it.  If this ever "
            "becomes a stable rule, you can drop preview=true but must "
            "verify PLW1514 still fires in a sample test run first."
        )


class TestLintWorkflow:
    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "lint.yml"

    def test_workflow_exists(self):
        assert self.WORKFLOW_PATH.exists(), (
            f"CI workflow missing: {self.WORKFLOW_PATH}"
        )

    def test_workflow_has_blocking_ruff_step(self):
        """The workflow must run a blocking ``ruff check .`` step
        (one without --exit-zero) so violations fail the job."""
        content = self.WORKFLOW_PATH.read_text(encoding="utf-8")
        # Look for the blocking step's named line + its command.  We want
        # at least one ``ruff check .`` that does NOT have ``--exit-zero``
        # nearby.
        # Split into lines and find ruff check invocations
        lines = content.splitlines()
        found_blocking = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("ruff check") and "--exit-zero" not in stripped:
                # Also check it's not piped to `|| true` which would mask
                # the exit code.
                window = " ".join(lines[i:i + 3])
                if "|| true" not in window:
                    found_blocking = True
                    break
        assert found_blocking, (
            "lint.yml no longer contains a blocking ``ruff check .`` step "
            "(one without --exit-zero and not masked by || true).  "
            "Restore it — the PLW1514 rule is only useful if CI actually "
            "fails on violation."
        )

    def test_workflow_yaml_is_valid(self):
        """Workflow file must parse as valid YAML (can't ship a broken
        CI config to main)."""
        import yaml
        content = self.WORKFLOW_PATH.read_text(encoding="utf-8")
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            pytest.fail(f"lint.yml is not valid YAML: {exc}")
        assert isinstance(parsed, dict)
        assert "jobs" in parsed


QUALITY_ADAPTER_PROBE = r"""
import assert from 'node:assert/strict'
import childProcess from 'node:child_process'
import { syncBuiltinESMExports } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const [adapter, repository, scenario, supplied] = process.argv.slice(1)
const outputs = JSON.parse(supplied ?? '{}')
const lint = path.basename(adapter) === 'lint.mjs'
const expected = [
    lint
        ? ['uv', 'tool', 'run', '--offline', '--from', 'ruff==0.15.10', 'ruff', 'check', 'catalyst']
        : ['uv', 'run', '--directory', 'catalyst', '--frozen', '--offline', '--extra', 'dev',
            '--extra', 'all', 'python', 'scripts/run_tests_parallel.py', '--quality-summary',
            '--include-integration', '--file-retries', '0', '--file-timeout', '300',
            '--jobs', '4', '--slice', '1/1', 'tests', '--', '-q'],
    ['npm', '--prefix', 'catalyst/apps/desktop', 'run', lint ? 'check:lint' : 'test:ui']
]
const calls = []
childProcess.spawnSync = (command, args, options) => {
    calls.push([command, ...args])
    assert.equal(options.cwd, repository)
    assert.equal(options.encoding, 'utf8')
    assert.equal(options.maxBuffer, 16 * 1024 * 1024)
    if (calls.length === 1) {
        if (!lint) {
            assert.equal(options.env.PYTEST_ADDOPTS, '')
            if (process.platform === 'darwin') {
                assert.equal(options.env.TMPDIR, '/tmp')
                assert.equal(options.env.TMP, '/tmp')
                assert.equal(options.env.TEMP, '/tmp')
            }
        }
        if (scenario === 'python-failure') return { status: 7, stderr: 'python check failed' }
        if (scenario === 'unavailable') return { error: { message: 'spawn uv ENOENT' } }
        if (scenario === 'signal') return { status: null, signal: 'SIGTERM' }
        return { status: 0, stdout: lint ? 'All checks passed!\n' : outputs.python ??
            'HERMES_TEST_SUMMARY ' + JSON.stringify({
                schema: 'hermes-test-summary/1', files: 1, completed: 1,
                file_failures: 0, unmeasured_files: 0, passed: 3, failed: 0,
                skipped: 0, errors: 0, xfailed: 0, xpassed: 0, deselected: 0
            }) + '\n' }
    }
    return {
        status: scenario === 'desktop-failure' ? 9 : 0,
        stdout: scenario === 'missing-summary' || lint ? '' : outputs.desktop ?? 'Tests  2 passed (2)\n'
    }
}
syncBuiltinESMExports()
process.on('exit', () => {
    const early = ['python-failure', 'unavailable', 'signal'].includes(scenario)
    assert.deepEqual(calls, expected.slice(0, early ? 1 : 2))
})
process.argv = [process.execPath, adapter, '--check']
await import(pathToFileURL(adapter).href)
"""


def _run_quality_adapter(adapter, scenario, cwd, outputs=None):
        return subprocess.run(
                [
                        "node", "--input-type=module", "--eval", QUALITY_ADAPTER_PROBE,
                        str(REPO_ROOT / "scripts" / "quality" / f"{adapter}.mjs"),
                        str(REPO_ROOT.parent), scenario, json.dumps(outputs or {}),
                ],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
        )


@pytest.mark.parametrize("adapter", ["lint", "test"])
@pytest.mark.parametrize(
        ("scenario", "exit_code"),
        [("success", 0), ("python-failure", 7), ("unavailable", 2),
         ("signal", 1), ("desktop-failure", 9)],
)
def test_quality_adapters_select_offline_tools_and_propagate_failures(adapter, scenario, exit_code, tmp_path):
        result = _run_quality_adapter(adapter, scenario, tmp_path)
        assert result.returncode == exit_code, result.stdout + result.stderr
        if adapter == "test" and scenario == "success":
                assert "test result: ok. 5 passed; 0 failed;" in result.stdout
        elif scenario != "success":
                assert "test result: ok." not in result.stdout


@pytest.mark.parametrize("adapter", ["lint", "test"])
def test_quality_adapters_reject_missing_check_argument(adapter, tmp_path):
        result = subprocess.run(
                ["node", str(REPO_ROOT / "scripts" / "quality" / f"{adapter}.mjs")],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=False,
        )
        assert result.returncode == 2
        assert "usage:" in result.stderr


def test_quality_adapter_requires_both_test_summaries(tmp_path):
        result = _run_quality_adapter("test", "missing-summary", tmp_path)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "quality summary unavailable" in result.stderr
        assert "test result: ok." not in result.stdout


@pytest.mark.parametrize("dimension", ["lint", "test"])
def test_quality_source_inputs_exist_and_bind_desktop_configuration(dimension):
        spec = json.loads((REPO_ROOT / "SPEC.json").read_text(encoding="utf-8"))
        contract = spec["quality_obligations"]["dimensions"][dimension]
        inputs = contract["source_inputs"]
        for source in inputs:
                if not any(character in source for character in "*?["):
                        assert (REPO_ROOT.parent / source).is_file(), source
        assert "catalyst/apps/desktop/package.json" in inputs
        assert "catalyst/apps/desktop/tsconfig*.json" in inputs
        assert "quine/canon/IGNORE-POLICY.json" in inputs
        if dimension == "lint":
                assert contract["tool"] == "ruff+tsc+eslint"
                assert set(contract["investment"]["tooling"]) == {"ruff", "tsc", "eslint"}
                assert "catalyst/eslint.config.shared.mjs" in inputs
                assert "catalyst/apps/desktop/eslint.config.mjs" in inputs
        else:
                assert contract["tool"] == "pytest+vitest"
                assert set(contract["investment"]["tooling"]) == {"pytest", "vitest"}
                assert "catalyst/scripts/quality/lint.mjs" in inputs
                assert "catalyst/apps/desktop/vitest.config.ts" in inputs
                assert "catalyst/apps/desktop/vitest.setup.ts" in inputs

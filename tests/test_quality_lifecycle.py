"""Exercise only synthetic, identity-retained process trees; never the live suite."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest


pytestmark = [
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX session ownership"),
    pytest.mark.live_system_guard_bypass,
]
ROOT = Path(__file__).resolve().parents[1]


def _wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError("bounded process fixture did not settle")


def _live(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _cleanup(processes):
    for process in reversed(processes):
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(processes, timeout=2)


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_stop_and_restart_reap_new_session_workers_and_service_descendants(
    tmp_path, wrapped, signum
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runner = scripts / "run_tests_parallel.py"
    runner.write_bytes((ROOT / "scripts" / "run_tests_parallel.py").read_bytes())
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    marker = tmp_path / "pids.json"
    # A stubborn new-session server is representative of test-launched gateways.
    (tests / "test_service.py").write_text(
        "import json, os, signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "def test_service():\n"
        "    server = subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], "
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"    Path({str(marker)!r}).write_text(json.dumps([os.getpid(), server.pid]))\n"
        "    time.sleep(60)\n",
        encoding="utf-8",
    )
    queued = tmp_path / "queued"
    (tests / "test_z_queued.py").write_text(
        f"from pathlib import Path\nPath({str(queued)!r}).touch()\ndef test_unused(): pass\n",
        encoding="utf-8",
    )
    args = [
        str(runner), "--quality-summary", "--jobs", "1", "--file-retries", "2",
        "--file-timeout", "60", "tests", "--", "-q",
    ]
    command = [sys.executable, *args]
    if wrapped:
        wrapper = tmp_path / "wrapper.mjs"
        wrapper.write_text(
            f"import {{ runCommand }} from {(ROOT / 'scripts/quality/command.mjs').as_uri()!r};\n"
            f"const result = await runCommand({sys.executable!r}, {json.dumps(args)}, "
            "{cwd: process.cwd(), env: process.env});\n"
            "process.stdout.write(result.stdout); process.stderr.write(result.stderr);\n"
            "process.exitCode = result.status ?? 130;\n",
            encoding="utf-8",
        )
        command = ["node", str(wrapper)]
    environment = {**os.environ, "PYTEST_ADDOPTS": "", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    tracked = []
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    sentinel_identity = psutil.Process(sentinel.pid)
    try:
        for _ in range(2):
            marker.unlink(missing_ok=True)
            owner = subprocess.Popen(
                command, cwd=tmp_path, env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            tracked.append(psutil.Process(owner.pid))
            try:
                _wait_for(marker.exists)
                worker_pid, server_pid = json.loads(marker.read_text(encoding="utf-8"))
                worker, server = psutil.Process(worker_pid), psutil.Process(server_pid)
                tracked.extend([worker, server])
                assert os.getsid(worker.pid) == worker.pid
                assert os.getsid(server.pid) == server.pid
                # Allow the runner's bounded observation to retain the detached service.
                time.sleep(0.25)
                owner.send_signal(signum)
                output, errors = owner.communicate(timeout=8)
                assert owner.returncode != 0, (output, errors)
                assert "HERMES_TEST_SUMMARY" not in output
                assert not queued.exists(), "shutdown must not start queued files or retries"
                _wait_for(lambda: not _live(worker) and not _live(server), seconds=3)
                assert _live(sentinel_identity), "unrelated process was signalled"
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=2)
    finally:
        _cleanup(tracked)
        sentinel.terminate()
        sentinel.wait(timeout=2)


def test_command_escalates_and_bounds_output_without_starting_a_next_command(tmp_path):
    wrapper = tmp_path / "overflow.mjs"
    wrapper.write_text(
        f"import {{ runCommand }} from {(ROOT / 'scripts/quality/command.mjs').as_uri()!r};\n"
        f"const result = await runCommand({sys.executable!r}, ['-c', "
        "'import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "sys.stdout.write(\"x\" * 4096); sys.stdout.flush(); time.sleep(60)'], "
        "{maxBuffer: 128});\n"
        "console.log(JSON.stringify({size: result.stdout.length, status: result.status, "
        "error: result.error?.message}));\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(wrapper)], cwd=tmp_path, capture_output=True, text=True, timeout=6,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result == {"size": 128, "status": None, "error": "stdout exceeded maxBuffer"}


@pytest.mark.parametrize("stop", [False, True])
def test_wrapper_closes_stubborn_group_members_even_when_the_leader_closes_its_pipes(tmp_path, stop):
    marker = tmp_path / "child"
    script = tmp_path / "leader.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"Path({str(marker)!r}).write_text(str(child.pid))\n"
        f"time.sleep({60 if stop else 0.3})\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "group.mjs"
    wrapper.write_text(
        f"import {{ runCommand }} from {(ROOT / 'scripts/quality/command.mjs').as_uri()!r};\n"
        f"const result = await runCommand({sys.executable!r}, [{str(script)!r}], {{}});\n"
        "process.exitCode = result.status ?? 130;\n",
        encoding="utf-8",
    )
    owner = subprocess.Popen(["node", str(wrapper)])
    tracked = [psutil.Process(owner.pid)]
    try:
        _wait_for(marker.exists)
        child = psutil.Process(int(marker.read_text(encoding="utf-8")))
        tracked.append(child)
        if stop:
            time.sleep(0.2)
            owner.terminate()
        assert owner.wait(timeout=5) == (130 if stop else 0)
        _wait_for(lambda: not _live(child), seconds=2)
    finally:
        _cleanup(tracked)
        owner.wait(timeout=2)

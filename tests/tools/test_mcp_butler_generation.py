import json

from tools import mcp_tool


def test_current_butler_binding_reads_stable_run_pointer(monkeypatch, tmp_path):
    package = tmp_path / "run/target/toolchains/butler/current/bin"
    package.mkdir(parents=True)
    (package / "lucid").write_bytes(b"native")
    (package / "butler").write_bytes(b"native")
    pointer = package.parent.parent / "current.json"
    pointer.write_text(
        json.dumps(
            {
                "schema": "ae-run-butler-pointer/1",
                "generation": "generation-next",
                "cache_key": "sha256:test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUTLER_REPOSITORY_ROOT", str(tmp_path))

    generation, resolved = mcp_tool._current_butler_binding()

    assert generation == "generation-next"
    assert resolved == package


def test_lucid_server_task_records_no_generation_before_connection():
    server = mcp_tool.MCPServerTask("LUCID")

    assert server._butler_generation is None

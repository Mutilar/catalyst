import json
import subprocess
from pathlib import Path


# Exercise the workspace extension with Catalyst's registered Node toolchain.
REPOSITORY = Path(__file__).parents[2]
PLUGIN = REPOSITORY / ".vscode" / "plugin"


def run_node(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", *arguments],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_vscode_lucid_plugin_parser_and_javascript_are_executable() -> None:
    parser_tests = run_node("--test", str(PLUGIN / "test" / "lucid-result.test.js"))
    assert parser_tests.returncode == 0, parser_tests.stdout + parser_tests.stderr

    for source in [PLUGIN / "extension.js", PLUGIN / "lucid-result.js"]:
        syntax = run_node("--check", str(source))
        assert syntax.returncode == 0, syntax.stdout + syntax.stderr


def test_vscode_lucid_plugin_manifests_are_valid_json() -> None:
    package = json.loads((PLUGIN / "package.json").read_text(encoding="utf-8"))
    launch = json.loads((REPOSITORY / ".vscode" / "launch.json").read_text(encoding="utf-8"))

    assert package["main"] == "./extension.js"
    assert package["contributes"]["commands"] == [
        {
            "command": "lucid.previewResult",
            "title": "LUCID: Preview Selected or Copied Result",
            "category": "LUCID",
        }
    ]
    assert launch["configurations"][0]["args"] == [
        "--extensionDevelopmentPath=${workspaceFolder}/.vscode/plugin"
    ]

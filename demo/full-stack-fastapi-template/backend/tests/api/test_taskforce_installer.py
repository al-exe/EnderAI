import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.taskforce.installer import CODEX_HOOKS, HOOKS, JQ_FILES
from app.main import app

INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install.sh"
CODEX_INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install-codex.sh"
REPO_ROOT = Path(__file__).resolve().parents[5]
CANONICAL_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-hooks"
CANONICAL_CODEX_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-codex-hooks"
PACKAGED_HOOK_DIR = (
    REPO_ROOT
    / "demo"
    / "full-stack-fastapi-template"
    / "backend"
    / "app"
    / "assets"
    / "taskforce-hooks"
)
PACKAGED_CODEX_HOOK_DIR = (
    REPO_ROOT
    / "demo"
    / "full-stack-fastapi-template"
    / "backend"
    / "app"
    / "assets"
    / "taskforce-codex-hooks"
)


@pytest.mark.parametrize("source_name", [hook[0] for hook in HOOKS])
def test_packaged_hook_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_HOOK_DIR / source_name
    ).read_bytes()


@pytest.mark.parametrize("source_name", [jq[0] for jq in JQ_FILES])
def test_packaged_jq_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_HOOK_DIR / source_name
    ).read_bytes()


@pytest.mark.parametrize("source_name", [hook[0] for hook in CODEX_HOOKS])
def test_packaged_codex_hook_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_CODEX_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_CODEX_HOOK_DIR / source_name
    ).read_bytes()


def get_installer_response():
    with TestClient(app) as client:
        return client.get(INSTALLER_URL)


def get_codex_installer_response():
    with TestClient(app) as client:
        return client.get(CODEX_INSTALLER_URL)


def test_installer_is_public_and_has_no_private_repo_dependency() -> None:
    response = get_installer_response()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert "raw.githubusercontent.com" not in response.text
    assert "github.com/al-exe/EnderAI" not in response.text
    for source_name, target_name, hook_name, timeout, _ in HOOKS:
        assert f"scripts/taskforce-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text
        assert f"merge_hook {hook_name}" in response.text
        assert str(timeout) in response.text
    for source_name, target_name, _ in JQ_FILES:
        assert f"scripts/taskforce-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text


def test_codex_installer_is_public_and_self_contained() -> None:
    response = get_codex_installer_response()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert "raw.githubusercontent.com" not in response.text
    for source_name, target_name, hook_name, matcher, timeout, _ in CODEX_HOOKS:
        assert f"scripts/taskforce-codex-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text
        assert f"merge_hook {hook_name}" in response.text
        assert matcher in response.text
        assert str(timeout) in response.text
    assert "run /hooks" in response.text


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_codex_installer_is_idempotent_and_preserves_existing_hooks(
    tmp_path: Path,
) -> None:
    response = get_codex_installer_response()
    home = tmp_path / "home"
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    hooks_file = codex_dir / "hooks.json"
    external_command = "/existing/session-start.sh"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": external_command,
                                    "timeout": 3,
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )

    env = {**os.environ, "HOME": str(home)}
    for _ in range(2):
        subprocess.run(
            ["bash"],
            input=response.text,
            text=True,
            env=env,
            check=True,
            capture_output=True,
        )

    hooks = json.loads(hooks_file.read_text())["hooks"]
    assert hooks["SessionStart"][0]["hooks"][0]["command"] == external_command
    for source_name, target_name, hook_name, matcher, timeout, _ in CODEX_HOOKS:
        installed_path = codex_dir / "hooks" / target_name
        assert (
            installed_path.read_bytes()
            == (CANONICAL_CODEX_HOOK_DIR / source_name).read_bytes()
        )
        matching = [
            hook
            for group in hooks[hook_name]
            for hook in group["hooks"]
            if hook["command"] == str(installed_path)
        ]
        assert matching == [
            {
                "type": "command",
                "command": str(installed_path),
                "timeout": timeout,
            }
        ]
        groups = [
            group
            for group in hooks[hook_name]
            if any(hook["command"] == str(installed_path) for hook in group["hooks"])
        ]
        assert groups[0]["matcher"] == matcher


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_codex_hooks_register_session_and_inject_discovery_context(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    capture_file = tmp_path / "payload.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
output_file=""
while (($#)); do
    case "$1" in
        --data)
            shift
            printf '%s' "$1" > "$CAPTURE_FILE"
            ;;
        -o)
            shift
            output_file="$1"
            ;;
    esac
    shift
done
if [[ "$output_file" != "/dev/null" ]]; then
    printf '%s' "$CURL_RESPONSE" > "$output_file"
    printf '200'
else
    printf '204'
fi
"""
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CAPTURE_FILE": str(capture_file),
        "CURL_RESPONSE": json.dumps(
            {
                "matches": [
                    {
                        "title": "Prior decision",
                        "score": 0.91,
                        "confidence_band": "high",
                        "summary_markdown": "Use the existing session archive.",
                        "outcome": None,
                    }
                ]
            }
        ),
    }

    subprocess.run(
        ["bash", str(CANONICAL_CODEX_HOOK_DIR / "session-start.sh")],
        input=json.dumps(
            {
                "session_id": "codex-session-1",
                "cwd": str(tmp_path),
                "model": "gpt-5.4",
                "source": "startup",
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    heartbeat = json.loads(capture_file.read_text())
    assert heartbeat["session_id"] == "codex-session-1"
    assert heartbeat["client"] == "codex"
    assert heartbeat["model_id"] == "gpt-5.4"

    prompt_result = subprocess.run(
        ["bash", str(CANONICAL_CODEX_HOOK_DIR / "user-prompt-submit.sh")],
        input=json.dumps(
            {
                "session_id": "codex-session-1",
                "cwd": str(tmp_path),
                "prompt": "Copy the Fleet behavior",
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    discover = json.loads(capture_file.read_text())
    assert discover["session_id"] == "codex-session-1"
    assert discover["client"] == "codex"
    assert discover["prompt"] == "Copy the Fleet behavior"
    assert "Prior decision" in prompt_result.stdout
    assert "Use the existing session archive." in prompt_result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_installer_is_idempotent_and_preserves_existing_stop_hook(
    tmp_path: Path,
) -> None:
    response = get_installer_response()
    assert response.status_code == 200

    home = tmp_path / "home"
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    settings_file = claude_dir / "settings.json"
    # A user-supplied Stop hook that the installer must leave untouched while
    # it merges in its own (record-usage, stop, …) commands.
    external_stop_command = "$HOME/.claude/hooks/my-custom-stop-hook.sh"
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/existing/user-prompt-hook.sh",
                                    "timeout": 3,
                                }
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "matcher": "*",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": external_stop_command,
                                    "timeout": 10,
                                }
                            ],
                        }
                    ],
                }
            }
        )
    )

    env = {**os.environ, "HOME": str(home)}
    for _ in range(2):
        subprocess.run(
            ["bash"],
            input=response.text,
            text=True,
            env=env,
            check=True,
            capture_output=True,
        )

    hooks = json.loads(settings_file.read_text())["hooks"]
    assert sorted(hooks) == [
        "PostToolUse",
        "SessionEnd",
        "Stop",
        "UserPromptSubmit",
    ]

    for source_name, target_name, hook_name, timeout, _ in HOOKS:
        installed_path = claude_dir / "hooks" / target_name
        assert (
            installed_path.read_bytes()
            == (CANONICAL_HOOK_DIR / source_name).read_bytes()
        )
        assert installed_path.stat().st_mode & 0o111

        expected_command = str(installed_path)
        matching = [
            hook
            for matcher in hooks[hook_name]
            for hook in matcher["hooks"]
            if hook["command"] == expected_command
        ]
        assert matching == [
            {
                "type": "command",
                "command": expected_command,
                "timeout": timeout,
            }
        ]

    for source_name, target_name, _ in JQ_FILES:
        installed_path = claude_dir / "hooks" / target_name
        assert (
            installed_path.read_bytes()
            == (CANONICAL_HOOK_DIR / source_name).read_bytes()
        )

    stop_commands = [
        hook["command"] for matcher in hooks["Stop"] for hook in matcher["hooks"]
    ]
    assert stop_commands.count(external_stop_command) == 1
    assert hooks["UserPromptSubmit"][0] == {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": "/existing/user-prompt-hook.sh",
                "timeout": 3,
            }
        ],
    }


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
@pytest.mark.parametrize(
    ("hook_name", "include_prompt"),
    [("post-tool-use.sh", False), ("stop.sh", True)],
)
def test_observe_hooks_clamp_payloads_and_report_model(
    tmp_path: Path,
    hook_name: str,
    include_prompt: bool,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-8",
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 7,
                        "cache_read_input_tokens": 3,
                        "cache_creation_input_tokens": 2,
                    },
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Bash",
                            "input": {"command": "x" * 2500},
                        },
                        {"type": "text", "text": "Implemented the checkpoint."},
                    ],
                },
            }
        )
        + "\n"
    )

    capture_file = tmp_path / "payload.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
while (($#)); do
    if [[ "$1" == "--data" ]]; then
        shift
        printf '%s' "$1" > "$CAPTURE_FILE"
    fi
    shift
done
printf '202'
"""
    )
    curl.chmod(0o755)

    hook_payload = {
        "session_id": f"hook-{hook_name}",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }
    if include_prompt:
        hook_payload["prompt"] = "p" * 9000

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CAPTURE_FILE": str(capture_file),
        "TASKFORCE_CHECKPOINT_EVERY": "1",
    }
    subprocess.run(
        ["bash", str(CANONICAL_HOOK_DIR / hook_name)],
        input=json.dumps(hook_payload),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )

    body = json.loads(capture_file.read_text())
    assert len(body["commands_run"][0]["cmd"]) <= 2000
    assert body["harness"]["model_id"] == "claude-opus-4-8"
    if include_prompt:
        assert len(body["prompt"]) <= 8000


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
@pytest.mark.parametrize("hook_name", ["post-tool-use.sh", "stop.sh"])
def test_observe_hooks_extract_user_text_and_command_output(
    tmp_path: Path,
    hook_name: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "merge"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_test",
                                    "name": "Bash",
                                    "input": {"command": "echo hi"},
                                }
                            ]
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_test",
                                    "content": "Error: No tests found.",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "Harness issue, not code."}
                            ]
                        },
                    }
                ),
            ]
        )
        + "\n"
    )

    capture_file = tmp_path / "payload.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
while (($#)); do
    if [[ "$1" == "--data" ]]; then
        shift
        printf '%s' "$1" > "$CAPTURE_FILE"
    fi
    shift
done
printf '202'
"""
    )
    curl.chmod(0o755)

    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CAPTURE_FILE": str(capture_file),
        "TASKFORCE_CHECKPOINT_EVERY": "1",
    }
    subprocess.run(
        ["bash", str(CANONICAL_HOOK_DIR / hook_name)],
        input=json.dumps(
            {
                "session_id": f"hook-transcript-{hook_name}",
                "transcript_path": str(transcript),
                "cwd": str(tmp_path),
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )

    body = json.loads(capture_file.read_text())
    assert body["transcript"] == [
        {"role": "user", "content": "merge"},
        {"role": "assistant", "content": "Harness issue, not code."},
    ]
    assert body["commands_run"] == [
        {
            "cmd": "echo hi",
            "exit_code": None,
            "output": "Error: No tests found.",
        }
    ]

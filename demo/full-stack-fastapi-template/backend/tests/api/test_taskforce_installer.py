import json
import os
import shutil
import subprocess
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.taskforce.installer import (
    CODEX_HOOKS,
    CURSOR_HOOKS,
    GIT_CONTEXT_FILES,
    HOOKS,
    JQ_FILES,
)
from app.main import app

INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install.sh"
CODEX_INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install-codex.sh"
CURSOR_INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install-cursor.sh"
REPO_ROOT = Path(__file__).resolve().parents[5]
CANONICAL_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-hooks"
CANONICAL_CODEX_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-codex-hooks"
CANONICAL_CURSOR_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-cursor-hooks"
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
PACKAGED_CURSOR_HOOK_DIR = (
    REPO_ROOT
    / "demo"
    / "full-stack-fastapi-template"
    / "backend"
    / "app"
    / "assets"
    / "taskforce-cursor-hooks"
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


@pytest.mark.parametrize("source_name", [hook[0] for hook in CURSOR_HOOKS])
def test_packaged_cursor_hook_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_CURSOR_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_CURSOR_HOOK_DIR / source_name
    ).read_bytes()


@pytest.mark.parametrize("source_name", [jq[0] for jq in JQ_FILES])
def test_packaged_cursor_jq_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_CURSOR_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_CURSOR_HOOK_DIR / source_name
    ).read_bytes()


def get_installer_response():
    with TestClient(app) as client:
        return client.get(INSTALLER_URL)


def get_codex_installer_response():
    with TestClient(app) as client:
        return client.get(CODEX_INSTALLER_URL)


def get_cursor_installer_response():
    with TestClient(app) as client:
        return client.get(CURSOR_INSTALLER_URL)


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


def test_cursor_installer_is_public_and_self_contained() -> None:
    response = get_cursor_installer_response()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert "raw.githubusercontent.com" not in response.text
    for source_name, target_name, hook_name, timeout, _ in CURSOR_HOOKS:
        assert f"scripts/taskforce-cursor-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text
        assert f"merge_hook {hook_name}" in response.text
        assert str(timeout) in response.text
    for source_name, target_name, _ in JQ_FILES:
        assert f"scripts/taskforce-cursor-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text
    for source_name, target_name, _ in GIT_CONTEXT_FILES:
        assert f"scripts/taskforce-cursor-hooks/{source_name}" in response.text
        assert f"$HOOK_DIR/{target_name}" in response.text
    assert "Settings -> Hooks" in response.text


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_git_context_resolves_branch_from_attachment(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "feature/foo"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    tracked = repo / "src" / "main.ts"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("export {}\n")
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Taskforce",
        "GIT_AUTHOR_EMAIL": "taskforce@example.com",
        "GIT_COMMITTER_NAME": "Taskforce",
        "GIT_COMMITTER_EMAIL": "taskforce@example.com",
    }
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=git_env,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = CANONICAL_CURSOR_HOOK_DIR / "git-context.sh"
    payload = json.dumps(
        {
            "workspace_roots": [str(workspace)],
            "attachments": [{"file_path": str(tracked)}],
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; taskforce_resolve_git_branch_from_payload "$2"',
            "bash",
            str(script),
            payload,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "feature/foo"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_cursor_installer_is_idempotent_and_preserves_existing_hooks(
    tmp_path: Path,
) -> None:
    response = get_cursor_installer_response()
    home = tmp_path / "home"
    cursor_dir = home / ".cursor"
    cursor_dir.mkdir(parents=True)
    hooks_file = cursor_dir / "hooks.json"
    external_command = "./hooks/existing-session-start.sh"
    hooks_file.write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "sessionStart": [
                        {"command": external_command, "timeout": 3},
                    ]
                },
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
    assert hooks["sessionStart"][0]["command"] == external_command
    for source_name, target_name, hook_name, timeout, _ in CURSOR_HOOKS:
        installed_path = cursor_dir / "hooks" / target_name
        assert (
            installed_path.read_bytes()
            == (CANONICAL_CURSOR_HOOK_DIR / source_name).read_bytes()
        )
        matching = [
            hook
            for hook in hooks[hook_name]
            if hook["command"] == f"./hooks/{target_name}"
        ]
        assert matching == [{"command": f"./hooks/{target_name}", "timeout": timeout}]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_cursor_hooks_register_session_and_discover(tmp_path: Path) -> None:
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
if [[ "$output_file" != "/dev/null" && "$output_file" != "" ]]; then
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
                ],
                "suggested_pin": "11111111-1111-1111-1111-111111111111",
            }
        ),
    }

    subprocess.run(
        ["bash", str(CANONICAL_CURSOR_HOOK_DIR / "session-start.sh")],
        input=json.dumps(
            {
                "session_id": "cursor-session-1",
                "cwd": str(tmp_path),
                "model": "composer-2.5",
                "composer_mode": "agent",
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    heartbeat = json.loads(capture_file.read_text())
    assert heartbeat["session_id"] == "cursor-session-1"
    assert heartbeat["client"] == "cursor"
    assert heartbeat["model_id"] == "composer-2.5"

    prompt_result = subprocess.run(
        ["bash", str(CANONICAL_CURSOR_HOOK_DIR / "before-submit-prompt.sh")],
        input=json.dumps(
            {
                "session_id": "cursor-session-1",
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
    assert discover["session_id"] == "cursor-session-1"
    assert discover["client"] == "cursor"
    assert discover["prompt"] == "Copy the Fleet behavior"
    assert json.loads(prompt_result.stdout) == {"continue": True}
    assert (
        home / ".taskforce" / "cursor-session-1.active"
    ).read_text() == "11111111-1111-1111-1111-111111111111"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_cursor_stop_hook_marks_turn_ended(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    turn_ended_file = tmp_path / "turn-ended.json"
    observe_file = tmp_path / "observe.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
output_file=""
url=""
while (($#)); do
    case "$1" in
        --data)
            shift
            data="$1"
            ;;
        -o)
            shift
            output_file="$1"
            ;;
        http*)
            url="$1"
            ;;
    esac
    shift
done
if [[ "$url" == *session/turn-ended* ]]; then
    printf '%s' "$data" > "$TURN_ENDED_FILE"
    printf '204'
elif [[ "$output_file" != "/dev/null" && "$output_file" != "" ]]; then
    printf '%s' "$data" > "$OBSERVE_FILE"
    printf '202'
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
        "TURN_ENDED_FILE": str(turn_ended_file),
        "OBSERVE_FILE": str(observe_file),
    }

    subprocess.run(
        ["bash", str(CANONICAL_CURSOR_HOOK_DIR / "stop.sh")],
        input=json.dumps(
            {
                "session_id": "cursor-session-stop",
                "cwd": str(tmp_path),
                "prompt": "Finish the Fleet row polish",
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )

    turn_ended = json.loads(turn_ended_file.read_text())
    assert turn_ended == {"session_id": "cursor-session-stop", "demo": False}


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_codex_installer_is_idempotent_and_preserves_existing_hooks(
    tmp_path: Path,
) -> None:
    response = get_codex_installer_response()
    home = tmp_path / "home"
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True)
    settings_file = codex_dir / "config.toml"
    external_command = "/existing/session-start.sh"
    settings_file.write_text(
        "\n".join(
            [
                "[features]",
                "hooks = false",
                "",
                "[[hooks.SessionStart]]",
                'matcher = "startup"',
                "",
                "[[hooks.SessionStart.hooks]]",
                'type = "command"',
                f'command = "{external_command}"',
                "timeout = 3",
                "",
            ]
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

    parsed = tomllib.loads(settings_file.read_text())
    assert parsed["features"]["hooks"] is True
    hooks = parsed["hooks"]
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
        http*)
            url="$1"
            ;;
    esac
    shift
done
if [[ "$output_file" != "/dev/null" ]]; then
    if [[ "$url" == *taskforce/fleet ]]; then
        printf '%s' "$CURL_FLEET_RESPONSE" > "$output_file"
    else
        printf '%s' "$CURL_RESPONSE" > "$output_file"
    fi
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
        "CURL_FLEET_RESPONSE": json.dumps(
            {
                "fleet_sessions": [
                    {
                        "id": "fleet-1",
                        "name": "Session 1",
                        "is_history": False,
                        "agents": [
                            {
                                "session_id": "codex-session-1",
                                "repo": "EnderAI",
                                "branch": "feature/self",
                                "status": "running",
                                "minutes_ago": 0,
                                "display_name": "Self session",
                                "summary_markdown": "Current session.",
                            },
                            {
                                "session_id": "sibling-session",
                                "repo": "EnderAI-frontend",
                                "branch": "feature/fleet",
                                "status": "waiting",
                                "minutes_ago": 2,
                                "display_name": "Fleet UI polish",
                                "summary_markdown": "Polishing Sessions grouping.",
                            },
                        ],
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
    assert "Taskforce live siblings" in prompt_result.stdout
    assert "EnderAI-frontend@feature/fleet" in prompt_result.stdout
    assert "Polishing Sessions grouping." in prompt_result.stdout


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_codex_observe_hook_posts_structured_session_context(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    observe_file = tmp_path / "observe.json"
    turn_ended_file = tmp_path / "turn-ended.json"
    transcript = tmp_path / "codex-session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-06-17T04:00:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "Fix the Codex Taskforce hooks",
                                }
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T04:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "arguments": json.dumps(
                                {
                                    "cmd": "codex --strict-config doctor --json --all",
                                    "workdir": str(tmp_path),
                                }
                            ),
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-06-17T04:00:02Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Codex hooks are wired.",
                                }
                            ],
                        },
                    }
                ),
            ]
        )
        + "\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
output_file=""
url=""
data=""
while (($#)); do
    case "$1" in
        --data)
            shift
            data="$1"
            ;;
        -o)
            shift
            output_file="$1"
            ;;
        http*)
            url="$1"
            ;;
    esac
    shift
done
if [[ "$url" == *session/turn-ended* ]]; then
    printf '%s' "$data" > "$TURN_ENDED_FILE"
    printf '204'
    exit 0
fi
if [[ "$url" == *session/inbox/claim* ]]; then
    printf '{}'
    exit 0
fi
printf '%s' "$data" > "$OBSERVE_FILE"
printf '%s' "$CURL_RESPONSE" > "$output_file"
printf '200'
"""
    )
    curl.chmod(0o755)
    document_id = "5477ef23-c561-4b1d-8e80-f46f7c193e59"
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "OBSERVE_FILE": str(observe_file),
        "TURN_ENDED_FILE": str(turn_ended_file),
        "CURL_RESPONSE": json.dumps(
            {
                "action": "created",
                "document_id": document_id,
                "reason": "ok",
            }
        ),
    }

    result = subprocess.run(
        ["bash", str(CANONICAL_CODEX_HOOK_DIR / "observe.sh")],
        input=json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "codex-session-1",
                "transcript_path": str(transcript),
                "cwd": str(tmp_path),
                "model": "gpt-5.5",
                "last_assistant_message": "Codex hooks are wired.",
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )

    assert json.loads(result.stdout) == {"continue": True, "suppressOutput": True}
    observe = json.loads(observe_file.read_text())
    assert observe["session_id"] == "codex-session-1"
    assert observe["client"] == "codex"
    assert observe["active_document_id"] is None
    assert observe["transcript"] == []
    assert observe["harness"]["model_id"] == "gpt-5.5"
    assert observe["summary_points"] == [
        "Fix the Codex Taskforce hooks",
        "Codex hooks are wired.",
    ]
    assert observe["details_sections"][0]["anchor_id"] == "codex-latest-turn"
    assert (
        "Latest user prompt: Fix the Codex Taskforce hooks"
        in observe["details_sections"][0]["markdown"]
    )
    assert observe["commands_run"] == [
        {
            "cmd": "codex --strict-config doctor --json --all",
            "exit_code": None,
            "output": None,
        }
    ]
    assert (home / ".taskforce" / "codex-session-1.active").read_text() == document_id
    assert json.loads(turn_ended_file.read_text()) == {
        "session_id": "codex-session-1",
        "demo": False,
    }


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required")
def test_codex_session_end_hook_marks_session_ended(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".taskforce_mcp_token").write_text("test-token")
    state_dir = home / ".taskforce"
    state_dir.mkdir()
    (state_dir / "codex-session-end.active").write_text(
        "5477ef23-c561-4b1d-8e80-f46f7c193e59"
    )
    (state_dir / "codex-session-end.codex-counter").write_text("3")

    capture_file = tmp_path / "payload.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
data=""
while (($#)); do
    case "$1" in
        --data)
            shift
            data="$1"
            ;;
    esac
    shift
done
printf '%s' "$data" > "$CAPTURE_FILE"
printf '202'
"""
    )
    curl.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CAPTURE_FILE": str(capture_file),
    }

    subprocess.run(
        ["bash", str(CANONICAL_CODEX_HOOK_DIR / "session-end.sh")],
        input=json.dumps(
            {
                "session_id": "codex-session-end",
                "cwd": str(tmp_path),
            }
        ),
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )

    payload = json.loads(capture_file.read_text())
    assert payload["kind"] == "session_end"
    assert payload["session_id"] == "codex-session-end"
    assert payload["client"] == "codex"
    assert not (state_dir / "codex-session-end.active").exists()
    assert not (state_dir / "codex-session-end.codex-counter").exists()


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
        {
            "role": "user",
            "content": "merge",
            "source_id": None,
            "occurred_at": None,
        },
        {
            "role": "assistant",
            "content": "Harness issue, not code.",
            "source_id": None,
            "occurred_at": None,
        },
    ]
    assert body["commands_run"] == [
        {
            "cmd": "echo hi",
            "exit_code": None,
            "source_id": "toolu_test",
            "occurred_at": None,
            "output": "Error: No tests found.",
        }
    ]

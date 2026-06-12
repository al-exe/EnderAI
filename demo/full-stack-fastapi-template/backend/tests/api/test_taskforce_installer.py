import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.taskforce.installer import HOOKS
from app.main import app

INSTALLER_URL = f"{settings.API_V1_STR}/v2/taskforce/install.sh"
REPO_ROOT = Path(__file__).resolve().parents[5]
CANONICAL_HOOK_DIR = REPO_ROOT / "scripts" / "taskforce-hooks"
PACKAGED_HOOK_DIR = (
    REPO_ROOT
    / "demo"
    / "full-stack-fastapi-template"
    / "backend"
    / "app"
    / "assets"
    / "taskforce-hooks"
)


@pytest.mark.parametrize("source_name", [hook[0] for hook in HOOKS])
def test_packaged_hook_matches_canonical_source(source_name: str) -> None:
    assert (PACKAGED_HOOK_DIR / source_name).read_bytes() == (
        CANONICAL_HOOK_DIR / source_name
    ).read_bytes()


def get_installer_response():
    with TestClient(app) as client:
        return client.get(INSTALLER_URL)


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
    metrics_command = "$HOME/.claude/hooks/taskforce-record-usage.sh"
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
                                    "command": metrics_command,
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
    assert sorted(hooks) == ["PostToolUse", "Stop", "UserPromptSubmit"]

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

    stop_commands = [
        hook["command"] for matcher in hooks["Stop"] for hook in matcher["hooks"]
    ]
    assert stop_commands.count(metrics_command) == 1
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

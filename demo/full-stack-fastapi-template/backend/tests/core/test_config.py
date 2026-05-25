from app.core.config import Settings, expand_cors_origin_aliases


def test_expand_cors_origin_aliases_adds_taskforce_www_variant() -> None:
    assert expand_cors_origin_aliases(["https://taskforce.tools"]) == [
        "https://taskforce.tools",
        "https://www.taskforce.tools",
    ]


def test_expand_cors_origin_aliases_adds_taskforce_apex_variant() -> None:
    assert expand_cors_origin_aliases(["https://www.taskforce.tools"]) == [
        "https://www.taskforce.tools",
        "https://taskforce.tools",
    ]


def test_expand_cors_origin_aliases_adds_enderai_www_variant() -> None:
    assert expand_cors_origin_aliases(["https://enderai.xyz"]) == [
        "https://enderai.xyz",
        "https://www.enderai.xyz",
    ]


def test_expand_cors_origin_aliases_adds_enderai_apex_variant() -> None:
    assert expand_cors_origin_aliases(["https://www.enderai.xyz"]) == [
        "https://www.enderai.xyz",
        "https://enderai.xyz",
    ]


def test_expand_cors_origin_aliases_deduplicates_configured_aliases() -> None:
    assert expand_cors_origin_aliases(
        ["https://taskforce.tools", "https://www.taskforce.tools"]
    ) == [
        "https://taskforce.tools",
        "https://www.taskforce.tools",
    ]


def test_expand_cors_origin_aliases_leaves_path_origins_unchanged() -> None:
    assert expand_cors_origin_aliases(["https://al-exe.github.io/EnderAI-frontend"]) == [
        "https://al-exe.github.io/EnderAI-frontend",
    ]


def test_settings_all_cors_origins_includes_taskforce_defaults() -> None:
    test_settings = Settings(
        PROJECT_NAME="Taskforce",
        POSTGRES_SERVER="localhost",
        POSTGRES_USER="postgres",
        SECRET_KEY="test-secret",
        FIRST_SUPERUSER="admin@example.com",
        FIRST_SUPERUSER_PASSWORD="test-password",
    )

    assert "https://taskforce.tools" in test_settings.all_cors_origins
    assert "https://www.taskforce.tools" in test_settings.all_cors_origins

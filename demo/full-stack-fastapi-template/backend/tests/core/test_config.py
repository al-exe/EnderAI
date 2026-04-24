from app.core.config import expand_cors_origin_aliases


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
        ["https://enderai.xyz", "https://www.enderai.xyz"]
    ) == [
        "https://enderai.xyz",
        "https://www.enderai.xyz",
    ]


def test_expand_cors_origin_aliases_leaves_path_origins_unchanged() -> None:
    assert expand_cors_origin_aliases(["https://al-exe.github.io/EnderAI-frontend"]) == [
        "https://al-exe.github.io/EnderAI-frontend",
    ]

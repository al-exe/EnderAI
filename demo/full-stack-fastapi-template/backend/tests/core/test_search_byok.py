"""BYOK encryption helpers — no DB, no HTTP."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.search import byok


@pytest.fixture(autouse=True)
def _enable_byok(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(byok.settings, "BYOK_ENCRYPTION_KEY", key)


def test_encrypt_decrypt_roundtrip() -> None:
    secret = "sk-ant-api03-abcdefghijklmnop"
    ct = byok.encrypt_api_key(secret)
    assert ct != secret.encode("utf-8")
    assert byok.decrypt_api_key(ct) == secret


def test_decrypt_rejects_wrong_key(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-ant-api03-abcdef"
    ct = byok.encrypt_api_key(secret)
    monkeypatch.setattr(
        byok.settings,
        "BYOK_ENCRYPTION_KEY",
        Fernet.generate_key().decode("utf-8"),
    )
    with pytest.raises(byok.ByokConfigurationError):
        byok.decrypt_api_key(ct)


def test_fingerprint_only_keeps_last_four() -> None:
    assert byok.fingerprint("sk-ant-api03-aaaaaaaaaaaWXYZ") == "…WXYZ"
    assert byok.fingerprint("abc") == "…abc"


def test_missing_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(byok.settings, "BYOK_ENCRYPTION_KEY", None)
    with pytest.raises(byok.ByokConfigurationError):
        byok.encrypt_api_key("anything")


def test_malformed_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(byok.settings, "BYOK_ENCRYPTION_KEY", "not-base64!")
    with pytest.raises(byok.ByokConfigurationError):
        byok.encrypt_api_key("anything")

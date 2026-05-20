"""Bring-Your-Own-Key store for Pro-tier Search.

Stores user-supplied Anthropic / OpenAI API keys Fernet-encrypted at
rest. The Fernet key is derived from ``settings.BYOK_ENCRYPTION_KEY``
(a 32-byte url-safe base64 string generated via
``cryptography.fernet.Fernet.generate_key()``). When the env var is
unset, the encryption helpers raise ``ByokConfigurationError`` so the
API surface can return a clean 503 instead of corrupting data.

Validation flow on key save:
    1. Round-trip-encrypt the candidate.
    2. Hit ``{provider}/v1/models`` with the candidate over HTTPS.
    3. On 200, persist + stamp ``last_validated_at``.
    4. On 401/403, raise ``ByokValidationError`` and discard.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class ByokConfigurationError(RuntimeError):
    """Raised when BYOK_ENCRYPTION_KEY is missing or malformed."""


class ByokValidationError(RuntimeError):
    """Raised when the supplied API key fails the live provider check."""

    def __init__(self, provider: str, status_code: int, body_excerpt: str):
        super().__init__(
            f"{provider} rejected the key (HTTP {status_code}): {body_excerpt}"
        )
        self.provider = provider
        self.status_code = status_code


def _fernet() -> Fernet:
    key = settings.BYOK_ENCRYPTION_KEY
    if not key:
        raise ByokConfigurationError(
            "BYOK_ENCRYPTION_KEY is not configured; BYOK is disabled."
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as e:
        raise ByokConfigurationError(
            f"BYOK_ENCRYPTION_KEY is not a valid Fernet key: {e}"
        ) from e


def encrypt_api_key(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise ByokConfigurationError(
            "Stored BYOK ciphertext could not be decrypted with the current "
            "BYOK_ENCRYPTION_KEY — has the key been rotated?"
        ) from e


def fingerprint(api_key: str) -> str:
    """Last 4 visible characters, suffixed with the prefix-style hint.

    We never decrypt to render the UI — only the fingerprint is
    cleartext at rest. Showing the trailing 4 chars is enough for the
    user to recognize their own key without exposing the secret."""

    if len(api_key) <= 4:
        return "…" + api_key
    return "…" + api_key[-4:]


# Per-provider /v1/models endpoints. Both providers accept a Bearer
# token and return a model list on success — we don't read the body,
# just the status code.
_PROVIDER_VALIDATION_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    # Anthropic uses x-api-key header, not Bearer, and a different
    # endpoint structure. Handled below.
}


async def validate_api_key(provider: str, api_key: str) -> None:
    """Round-trip the key against the provider's lightest list endpoint.

    Raises ``ByokValidationError`` on 4xx; lets 5xx bubble up so we
    don't lock users out when the provider is down."""

    async with httpx.AsyncClient(timeout=10.0) as client:
        if provider == "openai":
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        elif provider == "anthropic":
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
        else:
            raise ValueError(f"Unsupported BYOK provider: {provider!r}")

        if 400 <= resp.status_code < 500:
            excerpt = resp.text[:200] if resp.text else ""
            raise ByokValidationError(provider, resp.status_code, excerpt)
        resp.raise_for_status()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

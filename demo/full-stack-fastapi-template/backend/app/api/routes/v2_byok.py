"""Bring-Your-Own-Key CRUD for Pro-tier Search.

Endpoints:
    GET    /v2/byok            — list the current user's keys (metadata only)
    POST   /v2/byok            — validate + store a new key
    DELETE /v2/byok/{provider} — revoke a key (sets revoked_at)

The api_key value is never returned in any response — only the
``key_fingerprint`` is exposed."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.search.byok import (
    ByokConfigurationError,
    ByokValidationError,
    encrypt_api_key,
    fingerprint,
    now_utc,
    validate_api_key,
)
from app.models import (
    ByokCredential,
    ByokCredentialCreate,
    ByokCredentialPublic,
    ByokCredentialsPublic,
    Message,
)

router = APIRouter(prefix="/v2/byok", tags=["v2-byok"])


def _to_public(cred: ByokCredential) -> ByokCredentialPublic:
    return ByokCredentialPublic(
        provider=cred.provider,
        key_fingerprint=cred.key_fingerprint,
        created_at=cred.created_at,
        last_validated_at=cred.last_validated_at,
        revoked_at=cred.revoked_at,
    )


@router.get("", response_model=ByokCredentialsPublic)
def list_byok_credentials(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> ByokCredentialsPublic:
    rows = session.exec(
        select(ByokCredential).where(ByokCredential.user_id == current_user.id)
    ).all()
    return ByokCredentialsPublic(credentials=[_to_public(r) for r in rows])


@router.post(
    "",
    response_model=ByokCredentialPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_or_replace_byok_credential(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    body: ByokCredentialCreate,
) -> ByokCredentialPublic:
    # 1. Validate against the live provider before touching the DB. If
    #    the key is bad we surface a 400 with the upstream excerpt; no
    #    half-written row gets left behind.
    try:
        await validate_api_key(body.provider, body.api_key)
    except ByokValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{body.provider} rejected the key (HTTP {e.status_code}).",
        )
    except ByokConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # 2. Encrypt + upsert. One row per (user, provider).
    try:
        ciphertext = encrypt_api_key(body.api_key)
    except ByokConfigurationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    existing = session.exec(
        select(ByokCredential)
        .where(ByokCredential.user_id == current_user.id)
        .where(ByokCredential.provider == body.provider)
    ).first()

    now = now_utc()
    if existing is None:
        cred = ByokCredential(
            user_id=current_user.id,
            provider=body.provider,
            encrypted_api_key=ciphertext,
            key_fingerprint=fingerprint(body.api_key),
            created_at=now,
            last_validated_at=now,
        )
        session.add(cred)
    else:
        existing.encrypted_api_key = ciphertext
        existing.key_fingerprint = fingerprint(body.api_key)
        existing.last_validated_at = now
        existing.revoked_at = None
        session.add(existing)
        cred = existing
    session.commit()
    session.refresh(cred)
    return _to_public(cred)


@router.delete("/{provider}", response_model=Message)
def revoke_byok_credential(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    provider: Literal["anthropic", "openai"],
) -> Message:
    cred = session.exec(
        select(ByokCredential)
        .where(ByokCredential.user_id == current_user.id)
        .where(ByokCredential.provider == provider)
    ).first()
    if cred is None or cred.revoked_at is not None:
        # Idempotent: revoking a non-existent or already-revoked key is OK.
        return Message(message="OK")
    cred.revoked_at = now_utc()
    session.add(cred)
    session.commit()
    return Message(message="OK")

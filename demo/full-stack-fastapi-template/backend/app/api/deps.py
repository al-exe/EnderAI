from collections.abc import Generator, Iterable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlmodel import Session

from app.core import security
from app.core.config import settings
from app.core.db import engine
from app.models import AgentCredential, TokenPayload, User, get_datetime_utc

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


def get_db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


def decode_token_payload(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        return TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )


def validate_agent_credential_token(
    session: SessionDep,
    token_data: TokenPayload,
    *,
    expected_token_kind: str | Iterable[str],
) -> AgentCredential:
    expected_token_kinds = (
        {expected_token_kind}
        if isinstance(expected_token_kind, str)
        else set(expected_token_kind)
    )

    if token_data.token_kind not in expected_token_kinds:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    if (
        token_data.agent_credential_id is None
        or token_data.agent_credential_version is None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    credential = session.get(AgentCredential, token_data.agent_credential_id)
    if (
        not credential
        or credential.user_id != token_data.sub
        or credential.revoked_at is not None
        or credential.token_version != token_data.agent_credential_version
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    user = session.get(User, credential.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        credential.last_used_at = get_datetime_utc()
        credential.updated_at = credential.last_used_at
        session.add(credential)
        session.commit()
    return credential


def get_current_user(session: SessionDep, token: TokenDep) -> User:
    token_data = decode_token_payload(token)

    if token_data.token_kind in {"agent_credential", "agent_mcp"}:
        validate_agent_credential_token(
            session,
            token_data,
            expected_token_kind={"agent_credential", "agent_mcp"},
        )
    elif token_data.token_kind is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )

    user = session.get(User, token_data.sub)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if token_data.token_kind is None:
        user.last_seen_at = get_datetime_utc()
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_active_user(current_user: CurrentUser) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive users cannot write data",
        )
    return current_user


ActiveUser = Annotated[User, Depends(require_active_user)]


def get_current_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


def get_current_active_superuser(current_user: ActiveUser) -> User:
    return get_current_superuser(current_user)

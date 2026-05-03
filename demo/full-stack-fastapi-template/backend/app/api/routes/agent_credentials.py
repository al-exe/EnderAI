import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlmodel import select

from app.api.deps import (
    ActiveUser,
    CurrentUser,
    SessionDep,
    TokenDep,
    decode_token_payload,
    validate_agent_credential_token,
)
from app.core import security
from app.core.config import settings
from app.models import (
    AgentCredential,
    AgentCredentialCreate,
    AgentCredentialIssueResult,
    AgentCredentialPublic,
    AgentCredentialsPublic,
    AgentMcpTokenValidationResult,
    Message,
    User,
    get_datetime_utc,
)

router = APIRouter(prefix="/agent-credentials", tags=["agent-credentials"])


def _to_public(credential: AgentCredential) -> AgentCredentialPublic:
    return AgentCredentialPublic.model_validate(credential)


def _issue_agent_mcp_token(credential: AgentCredential) -> str:
    expires_delta = timedelta(days=settings.AGENT_CREDENTIAL_EXPIRE_DAYS)
    now = get_datetime_utc()
    expires_at = now + expires_delta

    credential.token_version += 1
    credential.updated_at = now
    credential.last_rotated_at = now
    credential.current_token_expires_at = expires_at

    mcp_access_token = security.create_access_token(
        credential.user_id,
        expires_delta=expires_delta,
        extra_claims={
            "token_kind": "agent_mcp",
            "agent_credential_id": str(credential.id),
            "agent_credential_version": credential.token_version,
        },
    )
    return mcp_access_token


def _to_issue_result(
    credential: AgentCredential,
    *,
    mcp_access_token: str,
) -> AgentCredentialIssueResult:
    return AgentCredentialIssueResult(
        credential=_to_public(credential),
        mcp_access_token=mcp_access_token,
    )


def _get_owned_credential(
    session: SessionDep, current_user: User, credential_id: uuid.UUID
) -> AgentCredential:
    credential = session.get(AgentCredential, credential_id)
    if not credential or credential.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Agent credential not found")
    return credential


@router.get("/", response_model=AgentCredentialsPublic)
def read_agent_credentials(
    session: SessionDep, current_user: CurrentUser
) -> AgentCredentialsPublic:
    statement = (
        select(AgentCredential)
        .where(AgentCredential.user_id == current_user.id)
        .order_by(AgentCredential.created_at.desc())
    )
    credentials = session.exec(statement).all()
    return AgentCredentialsPublic(
        data=[_to_public(credential) for credential in credentials],
        count=len(credentials),
    )


@router.post(
    "/",
    response_model=AgentCredentialIssueResult,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_credential(
    *,
    session: SessionDep,
    current_user: ActiveUser,
    body: AgentCredentialCreate,
) -> AgentCredentialIssueResult:
    now = get_datetime_utc()
    credential = AgentCredential(
        user_id=current_user.id,
        label=body.label,
        token_version=0,
        created_at=now,
        updated_at=now,
        last_rotated_at=now,
    )
    mcp_access_token = _issue_agent_mcp_token(credential)
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return _to_issue_result(
        credential,
        mcp_access_token=mcp_access_token,
    )


@router.post("/{credential_id}/rotate", response_model=AgentCredentialIssueResult)
def rotate_agent_credential(
    *,
    session: SessionDep,
    current_user: ActiveUser,
    credential_id: uuid.UUID,
) -> AgentCredentialIssueResult:
    credential = _get_owned_credential(session, current_user, credential_id)
    if credential.revoked_at is not None:
        raise HTTPException(
            status_code=400, detail="Revoked agent credentials cannot be rotated"
        )

    mcp_access_token = _issue_agent_mcp_token(credential)
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return _to_issue_result(
        credential,
        mcp_access_token=mcp_access_token,
    )


@router.post("/validate-mcp-token", response_model=AgentMcpTokenValidationResult)
def validate_mcp_token(
    *, session: SessionDep, token: TokenDep
) -> AgentMcpTokenValidationResult:
    token_data = decode_token_payload(token)
    credential = validate_agent_credential_token(
        session, token_data, expected_token_kind="agent_mcp"
    )
    return AgentMcpTokenValidationResult(
        credential_id=credential.id,
        user_id=credential.user_id,
    )


@router.delete("/{credential_id}", response_model=Message)
def revoke_agent_credential(
    *, session: SessionDep, current_user: ActiveUser, credential_id: uuid.UUID
) -> Message:
    credential = _get_owned_credential(session, current_user, credential_id)
    if credential.revoked_at is None:
        now = get_datetime_utc()
        credential.revoked_at = now
        credential.updated_at = now
        session.add(credential)
        session.commit()
    return Message(message="Agent credential revoked successfully")

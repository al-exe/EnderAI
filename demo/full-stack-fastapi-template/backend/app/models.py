import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import EmailStr
from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list["Item"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class AgentCredentialBase(SQLModel):
    label: str = Field(min_length=1, max_length=255)


class AgentCredentialCreate(AgentCredentialBase):
    pass


class AgentCredential(AgentCredentialBase, table=True):
    __tablename__ = "agent_credential"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        ondelete="CASCADE",
        index=True,
    )
    token_version: int = Field(default=1, nullable=False)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_rotated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    current_token_expires_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class AgentCredentialPublic(AgentCredentialBase):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_rotated_at: datetime | None = None
    current_token_expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class AgentCredentialsPublic(SQLModel):
    data: list[AgentCredentialPublic]
    count: int


class AgentCredentialIssueResult(SQLModel):
    credential: AgentCredentialPublic
    access_token: str
    backend_access_token: str
    mcp_access_token: str
    token_type: str = "bearer"


class AgentMcpTokenValidationResult(SQLModel):
    valid: bool = True
    credential_id: uuid.UUID
    user_id: uuid.UUID


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: str | None = Field(default=None, min_length=1, max_length=255)  # type: ignore


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# --- Artifacts (DB-backed; demo) ---

ArtifactKind = Literal["recipe", "pitfall", "decision", "checklist"]
PromotionMode = Literal["auto", "user"]


class ArtifactBase(SQLModel):
    workflow_key: str = Field(min_length=1)
    # NOTE: keep table-safe primitive types here; constrain via API schemas below.
    # SQLModel's table model creation will choke on `typing.Literal[...]`.
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body_mdc: str = Field(min_length=1)
    tags: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    source_refs: list[Any] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    promotion_mode: str = "auto"


class ArtifactCreate(ArtifactBase):
    kind: ArtifactKind = Field(min_length=1)
    promotion_mode: PromotionMode = "auto"


class ArtifactUpdate(SQLModel):
    workflow_key: str | None = Field(default=None, min_length=1)
    kind: ArtifactKind | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    body_mdc: str | None = Field(default=None, min_length=1)
    tags: dict[str, Any] | None = None
    source_refs: list[Any] | None = None
    promotion_mode: PromotionMode | None = None


class Artifact(ArtifactBase, table=True):
    __tablename__ = "artifact"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    superseded_by_id: uuid.UUID | None = Field(default=None, foreign_key="artifact.id")


class ArtifactPublic(ArtifactBase):
    id: uuid.UUID
    kind: ArtifactKind
    promotion_mode: PromotionMode
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    superseded_by_id: uuid.UUID | None = None


class ArtifactsPublic(SQLModel):
    data: list[ArtifactPublic]
    count: int


class WorkflowBucket(SQLModel, table=True):
    __tablename__ = "workflow_bucket"

    workflow_key: str = Field(primary_key=True, sa_type=Text)  # type: ignore[arg-type]
    bucket_name: str = Field(sa_type=Text)  # type: ignore[arg-type]
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class WorkflowKeyCount(SQLModel):
    workflow_key: str
    bucket_name: str
    count: int


class WorkflowKeysPublic(SQLModel):
    data: list[WorkflowKeyCount]


class WorkflowBucketCreate(SQLModel):
    workflow_key: str = Field(min_length=1)
    bucket_name: str = Field(min_length=1)


class WorkflowBucketUpdate(SQLModel):
    bucket_name: str = Field(min_length=1)


class WorkflowBucketPublic(SQLModel):
    workflow_key: str
    bucket_name: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkflowBucketsPublic(SQLModel):
    data: list[WorkflowBucketPublic]
    count: int


# --- Threads/Executions/Events/Artifact links (DB-backed; tables created via scripts) ---

ExecutionArtifactRelation = Literal["used", "created", "promoted", "superseded"]


class ThreadPublic(SQLModel):
    id: uuid.UUID
    title: str
    workflow_key: str
    intent_key: str | None = None
    goal: str | None = None
    acceptance_criteria: str | None = None
    systems_touched: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    risk_level: str = "read_only"
    status: str = "open"
    created_at: datetime | None = None
    last_touched_at: datetime | None = None


class ThreadCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    workflow_key: str = Field(min_length=1)
    intent_key: str | None = Field(default=None, min_length=1)
    goal: str | None = None
    acceptance_criteria: str | None = None
    systems_touched: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="read_only", min_length=1)
    status: str = Field(default="open", min_length=1)


class ThreadUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    workflow_key: str | None = Field(default=None, min_length=1)
    intent_key: str | None = Field(default=None, min_length=1)
    goal: str | None = None
    acceptance_criteria: str | None = None
    systems_touched: dict[str, Any] | None = None
    risk_level: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)


class ThreadsPublic(SQLModel):
    data: list[ThreadPublic]
    count: int


class ExecutionPublic(SQLModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    targets: list[Any] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "aborted"
    summary: str | None = None


class ExecutionCreate(SQLModel):
    targets: list[Any] = Field(default_factory=list)
    status: str = Field(default="running", min_length=1)
    summary: str | None = None


class ExecutionsPublic(SQLModel):
    data: list[ExecutionPublic]
    count: int


class ExecutionUpdate(SQLModel):
    targets: list[Any] | None = None
    ended_at: datetime | None = None
    status: str | None = Field(default=None, min_length=1)
    summary: str | None = None


class ExecutionStartRequest(SQLModel):
    thread: ThreadCreate
    execution: ExecutionCreate = Field(default_factory=ExecutionCreate)
    # If set, reuse the most recently touched Thread with the same (workflow_key, intent_key)
    # only if it was touched within this window.
    reuse_within_seconds: int | None = 60 * 60 * 24 * 30


class ExecutionStartPublic(SQLModel):
    thread: ThreadPublic
    execution: ExecutionPublic
    reused_thread: bool


class EventCreate(SQLModel):
    ts: datetime | None = None
    type: str = Field(min_length=1)
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class EventsPublic(SQLModel):
    data: list["EventPublic"]
    count: int


class ExecutionArtifactLinkCreate(SQLModel):
    artifact_id: uuid.UUID
    relation: ExecutionArtifactRelation
    created_at: datetime | None = None


class ExecutionArtifactLinksPublic(SQLModel):
    data: list["ExecutionArtifactLinkPublic"]
    count: int


class EventPublic(SQLModel):
    id: int
    execution_id: uuid.UUID
    ts: datetime | None = None
    type: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    supersedes_event_id: int | None = None


class ExecutionArtifactLinkPublic(SQLModel):
    relation: ExecutionArtifactRelation
    created_at: datetime | None = None
    artifact: ArtifactPublic


class ExecutionDetailPublic(SQLModel):
    execution: ExecutionPublic
    thread: ThreadPublic
    events: list[EventPublic]
    artifact_links: list[ExecutionArtifactLinkPublic]


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    # Access tokens are issued with `sub` = user id (UUID string). Keep it typed so
    # malformed tokens fail auth with 403 instead of leaking into DB lookups.
    sub: uuid.UUID
    token_kind: str | None = None
    agent_credential_id: uuid.UUID | None = None
    agent_credential_version: int | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

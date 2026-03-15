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


HypothesisStatus = Literal["open", "supported", "disproven"]
ChangeKind = Literal["code", "config", "infra", "docs", "test"]
ConfidenceLevel = Literal["high", "medium", "low"]


class CommandRecord(SQLModel):
    cmd: str = Field(min_length=1)
    purpose: str | None = None
    salient_result: str | None = None
    ts: datetime | None = None


class HypothesisRecord(SQLModel):
    statement: str = Field(min_length=1)
    status: HypothesisStatus = "open"
    evidence: str | None = None
    ts: datetime | None = None


class ChangeRecord(SQLModel):
    kind: ChangeKind = "code"
    summary: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    ts: datetime | None = None


class RelevantCaseSummary(SQLModel):
    case_id: uuid.UUID
    title: str
    short_summary: str | None = None
    outcome: str | None = None
    key_files: list[str] = Field(default_factory=list)
    key_symbols: list[str] = Field(default_factory=list)
    key_errors: list[str] = Field(default_factory=list)
    key_commands: list[str] = Field(default_factory=list)
    why_selected: str | None = None


class ContextPackSnapshot(SQLModel):
    topic_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    confidence: ConfidenceLevel | None = None
    alternative_topic_ids: list[uuid.UUID] = Field(default_factory=list)
    topic_summary: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    representative_cases: list[uuid.UUID] = Field(default_factory=list)
    recent_cases: list[uuid.UUID] = Field(default_factory=list)
    relevant_cases: list[RelevantCaseSummary] = Field(default_factory=list)
    canonical_files: list[str] = Field(default_factory=list)
    canonical_symbols: list[str] = Field(default_factory=list)
    canonical_errors: list[str] = Field(default_factory=list)
    canonical_symptoms: list[str] = Field(default_factory=list)
    pinned_takeaways: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    negative_history: list[str] = Field(default_factory=list)
    builder_version: str | None = None
    created_at: datetime | None = None


class CasePublic(SQLModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    title: str
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    status: str = "open"
    actor_id: uuid.UUID | None = None
    source: str | None = None
    input_summary: str | None = None
    summary_current: str | None = None
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    commands: list[CommandRecord] = Field(default_factory=list)
    hypotheses: list[HypothesisRecord] = Field(default_factory=list)
    changes: list[ChangeRecord] = Field(default_factory=list)
    outcome: str | None = None
    next_steps: list[str] = Field(default_factory=list)
    context_pack_snapshot: ContextPackSnapshot = Field(default_factory=ContextPackSnapshot)


class CasesPublic(SQLModel):
    data: list[CasePublic]
    count: int


class CaseUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str | None = Field(default=None, min_length=1)
    actor_id: uuid.UUID | None = None
    source: str | None = Field(default=None, min_length=1)
    input_summary: str | None = None
    summary_current: str | None = None
    files: list[str] | None = None
    symbols: list[str] | None = None
    errors: list[str] | None = None
    symptoms: list[str] | None = None
    commands: list[CommandRecord] | None = None
    hypotheses: list[HypothesisRecord] | None = None
    changes: list[ChangeRecord] | None = None
    outcome: str | None = None
    next_steps: list[str] | None = None
    context_pack_snapshot: ContextPackSnapshot | None = None


class CaseMemoView(SQLModel):
    case_id: uuid.UUID
    topic_id: uuid.UUID
    title: str
    status: str = "open"
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    input_summary: str | None = None
    summary_current: str | None = None
    files: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    commands: list[CommandRecord] = Field(default_factory=list)
    hypotheses: list[HypothesisRecord] = Field(default_factory=list)
    changes: list[ChangeRecord] = Field(default_factory=list)
    outcome: str | None = None
    next_steps: list[str] = Field(default_factory=list)


class CaseHydrationSignals(SQLModel):
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)


class CaseHydrationView(SQLModel):
    case_id: uuid.UUID
    topic_id: uuid.UUID
    title: str
    input_summary: str | None = None
    summary_current: str | None = None
    matched_signals: list[str] = Field(default_factory=list)
    signals: CaseHydrationSignals = Field(default_factory=CaseHydrationSignals)
    supported_hypotheses: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recent_changes: list[ChangeRecord] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    context_pack_snapshot: ContextPackSnapshot = Field(default_factory=ContextPackSnapshot)


class TopicRollupPublic(SQLModel):
    brief: str | None = None
    canonical_files: list[str] = Field(default_factory=list)
    canonical_symbols: list[str] = Field(default_factory=list)
    canonical_errors: list[str] = Field(default_factory=list)
    canonical_symptoms: list[str] = Field(default_factory=list)
    pinned_takeaways: list[str] = Field(default_factory=list)
    negative_history: list[str] = Field(default_factory=list)
    representative_case_ids: list[uuid.UUID] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    ambiguity_notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    case_count: int = 0
    recent_case_ids: list[uuid.UUID] = Field(default_factory=list)
    updated_at: datetime | None = None


class TopicPublic(SQLModel):
    id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    status: str = "open"
    workflow_key: str
    owner_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    rollup_summary: str | None = None
    rollup_version: int = 1
    canonical_files: list[str] = Field(default_factory=list)
    canonical_symbols: list[str] = Field(default_factory=list)
    canonical_errors: list[str] = Field(default_factory=list)
    canonical_symptoms: list[str] = Field(default_factory=list)
    pinned_takeaways: list[str] = Field(default_factory=list)
    ambiguity_notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    negative_history: list[str] = Field(default_factory=list)
    representative_case_ids: list[uuid.UUID] = Field(default_factory=list)
    recent_case_ids: list[uuid.UUID] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    case_count: int = 0


class TopicsPublic(SQLModel):
    data: list[TopicPublic]
    count: int


class TopicMatchRequest(SQLModel):
    title: str | None = None
    request_summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    limit: int = 5


class TopicHydrationPolicy(SQLModel):
    confidence: ConfidenceLevel = "low"
    max_topics: int = 1


class TopicMatchCandidate(SQLModel):
    topic: TopicPublic
    score: float
    confidence: ConfidenceLevel
    matched_signals: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)


class TopicMatchResult(SQLModel):
    policy: TopicHydrationPolicy = Field(default_factory=TopicHydrationPolicy)
    candidates: list[TopicMatchCandidate] = Field(default_factory=list)


class ContextPackBuildRequest(SQLModel):
    topic_id: uuid.UUID | None = None
    title: str | None = None
    request_summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    max_topics: int | None = None
    max_cases_per_topic: int = 3


class ContextPackBuildResult(SQLModel):
    policy: TopicHydrationPolicy = Field(default_factory=TopicHydrationPolicy)
    matched_topics: list[TopicMatchCandidate] = Field(default_factory=list)
    selected_topic_ids: list[uuid.UUID] = Field(default_factory=list)
    selected_case_ids: list[uuid.UUID] = Field(default_factory=list)
    relevant_cases: list[RelevantCaseSummary] = Field(default_factory=list)
    context_pack_snapshot: ContextPackSnapshot = Field(default_factory=ContextPackSnapshot)


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

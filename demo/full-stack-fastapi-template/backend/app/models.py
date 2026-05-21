import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pgvector.sqlalchemy import Vector
from pydantic import EmailStr
from sqlalchemy import DateTime, LargeBinary, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationBase(SQLModel):
    name: str = Field(min_length=1, max_length=255, unique=True, index=True)


class Organization(OrganizationBase, table=True):
    __tablename__ = "organization"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class OrganizationPublic(OrganizationBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrganizationsPublic(SQLModel):
    data: list[OrganizationPublic]
    count: int


class OrganizationInvitation(SQLModel, table=True):
    __tablename__ = "organization_invitation"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    invited_email: EmailStr = Field(index=True, max_length=255)
    invited_by_user_id: uuid.UUID = Field(
        foreign_key="user.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    accepted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class OrganizationInvitationCreate(SQLModel):
    email: EmailStr = Field(max_length=255)


class OrganizationInvitationPublic(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    organization_name: str | None = None
    invited_email: EmailStr
    invited_by_user_id: uuid.UUID
    created_at: datetime | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class OrganizationMemberPublic(SQLModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    organization_role: Literal["admin", "member"]


class OrganizationMemberUpdate(SQLModel):
    organization_role: Literal["admin", "member"]


class OrganizationMePublic(OrganizationPublic):
    organization_role: Literal["admin", "member"]
    members: list[OrganizationMemberPublic] = Field(default_factory=list)
    invitations: list[OrganizationInvitationPublic] = Field(default_factory=list)


class OrganizationInvitationsPublic(SQLModel):
    data: list[OrganizationInvitationPublic]
    count: int


class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        index=True,
        ondelete="SET NULL",
    )
    organization_role: str = Field(default="admin", index=True, max_length=16)


class UserCreate(UserBase):
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    is_active: bool = Field(default=True)
    hashed_password: str | None = None
    firebase_uid: str | None = Field(
        default=None,
        index=True,
        unique=True,
        max_length=128,
    )
    v2: bool = Field(default=False, nullable=False)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_seen_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    demo_seeded_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    stripe_customer_id: str | None = Field(
        default=None,
        index=True,
        unique=True,
        max_length=255,
    )
    stripe_subscription_id: str | None = Field(
        default=None,
        index=True,
        unique=True,
        max_length=255,
    )
    stripe_subscription_status: str | None = Field(
        default=None,
        index=True,
        max_length=64,
    )
    stripe_subscription_current_period_end: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    stripe_subscription_cancel_at_period_end: bool = False
    stripe_price_id: str | None = Field(default=None, max_length=255)


class UserPublic(UserBase):
    id: uuid.UUID
    v2: bool = False
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    stripe_subscription_status: str | None = None
    stripe_subscription_current_period_end: datetime | None = None
    stripe_subscription_cancel_at_period_end: bool = False
    stripe_price_id: str | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class BillingStatusPublic(SQLModel):
    has_customer: bool = False
    subscription_status: str | None = None
    subscription_current_period_end: datetime | None = None
    subscription_cancel_at_period_end: bool = False
    price_id: str | None = None
    is_subscription_active: bool = False


class BillingCheckoutSessionCreate(SQLModel):
    tier: Literal["pro", "max"]


class BillingSessionPublic(SQLModel):
    url: str


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
    mcp_access_token: str
    token_type: str = "bearer"


class AgentMcpTokenValidationResult(SQLModel):
    valid: bool = True
    credential_id: uuid.UUID
    user_id: uuid.UUID


class Topic(SQLModel, table=True):
    __tablename__ = "topic"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(index=True, unique=True, max_length=255)
    workflow_key: str = Field(index=True, unique=True, max_length=255)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    status: str = Field(default="open", min_length=1, max_length=64)
    is_demo: bool = Field(default=False, index=True)
    owner_ids: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    last_used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore[arg-type]
    rollup_summary: str | None = None
    rollup_version: int = 1
    rollup_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]


class CaseRecord(SQLModel, table=True):
    __tablename__ = "case_record"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    topic_id: uuid.UUID = Field(
        foreign_key="topic.id", nullable=False, index=True, ondelete="CASCADE"
    )
    title: str = Field(min_length=1, max_length=255)
    opened_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    closed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore[arg-type]
    status: str = Field(default="open", min_length=1, max_length=64)
    actor_id: uuid.UUID | None = None
    source: str | None = None
    input_summary: str | None = None
    summary_current: str | None = None
    case_data: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    context_pack_snapshot: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]


class Skill(SQLModel, table=True):
    __tablename__ = "skill"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(min_length=1, max_length=255)
    slug: str = Field(index=True, max_length=255)
    description: str | None = None
    status: str = Field(default="published", min_length=1, max_length=64)
    source_type: str = Field(default="topic", min_length=1, max_length=64)
    source_topic_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="topic.id",
        index=True,
        ondelete="SET NULL",
    )
    source_case_ids: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    owner_ids: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    is_demo: bool = Field(default=False, index=True)
    trigger_phrases: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    files: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    symbols: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    errors: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    symptoms: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    instructions_md: str
    confidence: str = Field(default="medium", min_length=1, max_length=16)
    source_snapshot: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    usage_count: int = 0
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    last_used_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))  # type: ignore[arg-type]


class CaseEvent(SQLModel, table=True):
    __tablename__ = "case_event"

    id: int | None = Field(default=None, primary_key=True)
    case_id: uuid.UUID = Field(
        foreign_key="case_record.id", nullable=False, index=True, ondelete="CASCADE"
    )
    ts: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    type: str = Field(min_length=1, max_length=128)
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    supersedes_event_id: int | None = Field(default=None, foreign_key="case_event.id")


class TopicMatchSignals(SQLModel):
    title: str | None = None
    request_summary: str | None = None
    aliases: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)


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


class TopicCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    workflow_key: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    status: str = Field(default="open", min_length=1)
    owner_ids: list[uuid.UUID] = Field(default_factory=list)


class TopicUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    workflow_key: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    aliases: list[str] | None = None
    status: str | None = Field(default=None, min_length=1)
    owner_ids: list[uuid.UUID] | None = None


class TopicMatchRequest(TopicMatchSignals):
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


class CasePublic(SQLModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    topic_title: str | None = None
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
    context_pack_snapshot: ContextPackSnapshot = Field(
        default_factory=ContextPackSnapshot
    )


class CasesPublic(SQLModel):
    data: list[CasePublic]
    count: int


class SearchRouteSearch(SQLModel):
    topicId: str | None = None
    caseId: str | None = None
    skillId: str | None = None


class SearchHitPublic(SQLModel):
    kind: Literal["topic", "case", "skill"]
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    excerpt: str | None = None
    updated_at: datetime | None = None
    route: Literal["/topics", "/cases", "/skills"]
    route_search: SearchRouteSearch = Field(default_factory=SearchRouteSearch)


class SearchResultsPublic(SQLModel):
    topics: list[SearchHitPublic] = Field(default_factory=list)
    cases: list[SearchHitPublic] = Field(default_factory=list)
    skills: list[SearchHitPublic] = Field(default_factory=list)
    topic_count: int = 0
    case_count: int = 0
    skill_count: int = 0


class CaseCreate(SQLModel):
    topic_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: str = Field(default="open", min_length=1)
    actor_id: uuid.UUID | None = None
    source: str | None = Field(default=None, min_length=1)
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
    context_pack_snapshot: ContextPackSnapshot | None = None


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


class CaseEventCreate(SQLModel):
    ts: datetime | None = None
    type: str = Field(min_length=1)
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class CaseEventPublic(SQLModel):
    id: int
    case_id: uuid.UUID
    ts: datetime | None = None
    type: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class CaseEventsPublic(SQLModel):
    data: list[CaseEventPublic]
    count: int


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
    context_pack_snapshot: ContextPackSnapshot = Field(
        default_factory=ContextPackSnapshot
    )


class ContextPackBuildRequest(TopicMatchSignals):
    topic_id: uuid.UUID | None = None
    max_topics: int | None = None
    max_cases_per_topic: int = 3


class ContextPackBuildResult(SQLModel):
    policy: TopicHydrationPolicy = Field(default_factory=TopicHydrationPolicy)
    matched_topics: list[TopicMatchCandidate] = Field(default_factory=list)
    selected_topic_ids: list[uuid.UUID] = Field(default_factory=list)
    selected_case_ids: list[uuid.UUID] = Field(default_factory=list)
    relevant_cases: list[RelevantCaseSummary] = Field(default_factory=list)
    context_pack_snapshot: ContextPackSnapshot = Field(
        default_factory=ContextPackSnapshot
    )


SkillSourceType = Literal["topic", "case", "context_pack", "demo", "manual"]
SkillStatus = Literal["draft", "published", "archived"]


class SkillPublic(SQLModel):
    id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    status: str = "published"
    source_type: str = "topic"
    source_topic_id: uuid.UUID | None = None
    source_case_ids: list[uuid.UUID] = Field(default_factory=list)
    owner_ids: list[uuid.UUID] = Field(default_factory=list)
    is_demo: bool = False
    trigger_phrases: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    instructions_md: str
    confidence: ConfidenceLevel = "medium"
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    usage_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None


class SkillsPublic(SQLModel):
    data: list[SkillPublic]
    count: int


class SkillGenerateRequest(SQLModel):
    topic_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    context_pack: ContextPackBuildRequest | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: SkillStatus = "published"
    force_refresh: bool = False


class SkillMatchRequest(TopicMatchSignals):
    limit: int = 5


class SkillMatchCandidate(SQLModel):
    skill: SkillPublic
    score: float
    confidence: ConfidenceLevel
    matched_signals: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)


class SkillMatchResult(SQLModel):
    candidates: list[SkillMatchCandidate] = Field(default_factory=list)


class SkillUseRequest(TopicMatchSignals):
    skill_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    max_skills: int = Field(default=3, ge=1, le=10)


class SkillUseResult(SQLModel):
    selected_skill: SkillPublic | None = None
    matched_skills: list[SkillMatchCandidate] = Field(default_factory=list)
    instructions_md: str | None = None
    confidence: ConfidenceLevel = "low"
    matched_signals: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    agent_usage_note: str


class V2DocumentSegment(SQLModel):
    text: str
    evidence_anchor_id: str | None = None


class V2DocumentParagraph(SQLModel):
    segments: list[V2DocumentSegment] = Field(default_factory=list)


class V2DocumentDetailsSection(SQLModel):
    anchor_id: str
    markdown: str


class V2DocumentFolder(SQLModel, table=True):
    __tablename__ = "v2_document_folder"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True, ondelete="CASCADE"
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        index=True,
        ondelete="SET NULL",
    )
    parent_folder_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="v2_document_folder.id",
        index=True,
        ondelete="SET NULL",
    )
    name: str = Field(min_length=1, max_length=255, index=True)
    visibility: str = Field(default="private", index=True, max_length=16)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]


class V2DocumentShare(SQLModel, table=True):
    __tablename__ = "v2_document_share"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "user_id",
            name="uq_v2_document_share_document_user",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="v2_document.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True, ondelete="CASCADE"
    )
    permission: str = Field(default="editor", index=True, max_length=16)
    created_by_user_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        index=True,
        ondelete="SET NULL",
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]


class V2DocumentFavorite(SQLModel, table=True):
    __tablename__ = "v2_document_favorite"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "user_id",
            name="uq_v2_document_favorite_document_user",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="v2_document.id",
        nullable=False,
        index=True,
        ondelete="CASCADE",
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True, ondelete="CASCADE"
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]


class V2Document(SQLModel, table=True):
    __tablename__ = "v2_document"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True, ondelete="CASCADE"
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        index=True,
        ondelete="SET NULL",
    )
    folder_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="v2_document_folder.id",
        index=True,
        ondelete="SET NULL",
    )
    visibility: str = Field(default="private", index=True, max_length=16)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    human_summary: str = Field(default="")
    ai_generated_summary: str = Field(default="")
    collaborators: list[str] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    main_body: list[dict[str, Any]] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    details_file_name: str = Field(default="")
    details_markdown_sections: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_type=JSONB,  # type: ignore[arg-type]
    )
    summary_tokens: int = Field(default=0, nullable=False)
    details_tokens: int = Field(default=0, nullable=False)
    is_demo: bool = Field(default=False, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    # Search indexing drift markers. NULL `last_indexed_at` means the
    # cron-sweep hasn't seen this document yet; index_version lets us
    # invalidate the whole corpus when the chunking/embedding strategy
    # changes (bump the constant in app/core/search/indexing.py).
    last_indexed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    index_version: str | None = Field(default=None, max_length=16)


class V2DocumentCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    human_summary: str = ""
    ai_generated_summary: str = ""
    collaborators: list[str] = Field(default_factory=list)
    main_body: list[V2DocumentParagraph] = Field(default_factory=list)
    details_file_name: str = ""
    details_markdown_sections: list[V2DocumentDetailsSection] = Field(
        default_factory=list
    )
    visibility: Literal["private", "organization"] = "private"
    folder_id: uuid.UUID | None = None
    # Optional usage payload — when present, the create handler records a
    # paired tokens.consumed (and any tokens.saved.*) metrics events.
    usage: "TaskforceUsagePayload | None" = None


class V2DocumentUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    human_summary: str | None = None
    ai_generated_summary: str | None = None
    collaborators: list[str] | None = None
    main_body: list[V2DocumentParagraph] | None = None
    details_file_name: str | None = None
    details_markdown_sections: list[V2DocumentDetailsSection] | None = None
    visibility: Literal["private", "organization"] | None = None
    folder_id: uuid.UUID | None = None
    # Owner-only overrides for the displayed timestamps. When the owner edits
    # these from the document page we trust the new value rather than
    # auto-bumping updated_at to "now" inside apply_v2_document_update.
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Optional usage payload — same semantics as V2DocumentCreate.usage.
    usage: "TaskforceUsagePayload | None" = None


class V2DocumentFolderCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    visibility: Literal["private", "organization"] = "private"
    parent_folder_id: uuid.UUID | None = None


class V2DocumentFolderUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: Literal["private", "organization"] | None = None
    parent_folder_id: uuid.UUID | None = None


class V2DocumentFolderPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None
    parent_folder_id: uuid.UUID | None
    name: str
    visibility: Literal["private", "organization"]
    created_at: datetime | None
    updated_at: datetime | None


class V2DocumentFoldersPublic(SQLModel):
    data: list[V2DocumentFolderPublic]
    count: int


class V2DocumentShareAssignment(SQLModel):
    user_id: uuid.UUID
    permission: Literal["viewer", "editor"] = "editor"


class V2DocumentSharesUpdate(SQLModel):
    shares: list[V2DocumentShareAssignment] = Field(default_factory=list)


class V2DocumentSharePublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    permission: Literal["viewer", "editor"]
    created_at: datetime | None
    updated_at: datetime | None


class V2DocumentSharesPublic(SQLModel):
    data: list[V2DocumentSharePublic]
    count: int


class V2DocumentPublic(SQLModel):
    id: uuid.UUID
    title: str
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None
    folder_id: uuid.UUID | None
    folder_name: str | None = None
    visibility: Literal["private", "organization"]
    user_access: Literal["owner", "editor", "viewer"] = "owner"
    is_favorite: bool = False
    description: str
    human_summary: str
    ai_generated_summary: str
    collaborators: list[str]
    shared_with: list[V2DocumentSharePublic] = Field(default_factory=list)
    main_body: list[V2DocumentParagraph]
    details_file_name: str
    details_markdown_sections: list[V2DocumentDetailsSection]
    is_demo: bool
    created_at: datetime | None
    updated_at: datetime | None


class V2DocumentsPublic(SQLModel):
    data: list[V2DocumentPublic]
    count: int


class Message(SQLModel):
    message: str


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(SQLModel):
    sub: uuid.UUID
    token_kind: str | None = None
    agent_credential_id: uuid.UUID | None = None
    agent_credential_version: int | None = None


class FirebaseTokenExchange(SQLModel):
    id_token: str = Field(min_length=1)
    full_name: str | None = Field(default=None, max_length=255)


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


# ----- Taskforce Metrics ----------------------------------------------------
#
# Append-only event log + read-side daily rollup + versioned model-pricing
# catalog. See docs/taskforce-metrics-engine-plan.md for the full design.
# Phase 1 ships only the tables, seed catalog, and pricing-lookup helper —
# no endpoints, no emitters, no rollup job yet.


class ModelPricing(SQLModel, table=True):
    """Versioned pricing snapshot. Every metrics_event with a USD figure FKs
    here so historical dollar values stay reproducible across price changes."""

    __tablename__ = "model_pricing"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "effective_from",
            name="uq_model_pricing_model_effective_from",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    provider: str = Field(min_length=1, max_length=64, index=True)
    model_id: str = Field(min_length=1, max_length=128, index=True)
    effective_from: datetime = Field(
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    effective_to: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    currency: str = Field(default="USD", min_length=3, max_length=8)
    input_per_mtok: Decimal = Field(sa_type=Numeric(10, 4))  # type: ignore
    output_per_mtok: Decimal = Field(sa_type=Numeric(10, 4))  # type: ignore
    cache_read_per_mtok: Decimal | None = Field(
        default=None,
        sa_type=Numeric(10, 4),  # type: ignore
    )
    cache_write_5m_per_mtok: Decimal | None = Field(
        default=None,
        sa_type=Numeric(10, 4),  # type: ignore
    )
    cache_write_1h_per_mtok: Decimal | None = Field(
        default=None,
        sa_type=Numeric(10, 4),  # type: ignore
    )
    batch_discount: Decimal | None = Field(
        default=None,
        sa_type=Numeric(4, 3),  # type: ignore
    )
    source_url: str | None = Field(default=None, max_length=512)
    recorded_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class MetricsEvent(SQLModel, table=True):
    """Append-only Taskforce metrics event. Per-kind extras live in `payload`."""

    __tablename__ = "metrics_event"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    occurred_at: datetime = Field(
        sa_type=DateTime(timezone=True),  # type: ignore
        index=True,
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, index=True, ondelete="CASCADE"
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        index=True,
        ondelete="SET NULL",
    )
    document_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="v2_document.id",
        index=True,
        ondelete="SET NULL",
    )
    kind: str = Field(min_length=1, max_length=64, index=True)
    model_id: str | None = Field(default=None, max_length=128)
    pricing_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="model_pricing.id",
        ondelete="SET NULL",
    )
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    cache_read_tokens: int | None = Field(default=None)
    cache_write_tokens: int | None = Field(default=None)
    usd_amount: Decimal | None = Field(
        default=None,
        sa_type=Numeric(12, 6),  # type: ignore
    )
    is_demo: bool = Field(default=False, nullable=False, index=True)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_type=JSONB,  # type: ignore
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


class MetricsDailyRollup(SQLModel, table=True):
    """Daily rollup, keyed (day, user, is_demo, metric_name). Read path."""

    __tablename__ = "metrics_daily_rollup"

    day: date = Field(primary_key=True)
    user_id: uuid.UUID = Field(
        primary_key=True,
        foreign_key="user.id",
        ondelete="CASCADE",
    )
    is_demo: bool = Field(primary_key=True, default=False)
    metric_name: str = Field(primary_key=True, min_length=1, max_length=64)
    organization_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="organization.id",
        index=True,
        ondelete="SET NULL",
    )
    value_num: Decimal = Field(sa_type=Numeric(20, 6))  # type: ignore
    value_count: int = Field(default=0)
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )


# Event kinds emitted into metrics_event.kind. Kept as module-level constants
# rather than a StrEnum so the values are stable in jsonb payloads and easy
# to grep.
METRICS_EVENT_DOCUMENT_CREATED = "document.created"
METRICS_EVENT_DOCUMENT_UPDATED = "document.updated"
METRICS_EVENT_DOCUMENT_REUSED = "document.reused"
METRICS_EVENT_DOCUMENT_FINISHED = "document.finished"
METRICS_EVENT_TOKENS_CONSUMED = "tokens.consumed"
METRICS_EVENT_TOKENS_SAVED_CACHE = "tokens.saved.cache"
METRICS_EVENT_TOKENS_SAVED_SUMMARY_ONLY = "tokens.saved.summary_only"
METRICS_EVENT_TOKENS_SAVED_REUSE = "tokens.saved.reuse"


class TaskforceUsagePayload(SQLModel):
    """Per-turn token usage reported by the agent.

    Mirrors the shape returned by the Anthropic SDK's ``message.usage``.
    All token counts default to 0 so partial reports (e.g. cache only) are
    expressible without filling every field.
    """

    model_id: str = Field(min_length=1, max_length=128)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    view_consulted: Literal["summary", "details", "both"] | None = None
    occurred_at: datetime | None = None


class MetricsEventPublic(SQLModel):
    """Response shape returned by the /usage endpoint."""

    id: uuid.UUID
    kind: str
    occurred_at: datetime
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    usd_amount: Decimal | None = None


class MetricsUsageRecorded(SQLModel):
    """Envelope returned by POST /v2/documents/{id}/usage and /reused.

    Lists every event the call produced — typically one primary event
    (``tokens.consumed`` or ``document.reused``) plus zero or more
    ``tokens.saved.*`` rows, depending on which savings sources fired.
    """

    events: list[MetricsEventPublic]


class TaskforceReusePayload(SQLModel):
    """Reuse context posted by the MCP layer after enderai_begin_document
    decides to reuse an existing document.

    Mirrors the shape of the scoring engine's Decision. ``score`` and
    ``band`` come from the chosen candidate's ``CongruenceScore``;
    ``reasons`` is the same human-readable list the MCP shows the agent.
    """

    score: int | None = Field(default=None, ge=0, le=100)
    band: Literal["high", "medium", "low", "explicit", "forced-new"] | None = None
    reasons: list[str] = Field(default_factory=list)
    usage: TaskforceUsagePayload | None = None


# ----- Metrics read-side public shapes -------------------------------------


class MetricPresentationPublic(SQLModel):
    format: Literal["compact-int", "usd", "ratio", "count"] = "compact-int"
    trend: bool = True
    icon: str | None = None


class MetricDefinitionPublic(SQLModel):
    name: str
    display_name: str
    unit: Literal["tokens", "usd", "count", "ratio"]
    description: str
    presentation: MetricPresentationPublic


class MetricDefinitionsResponse(SQLModel):
    data: list[MetricDefinitionPublic]


class MetricSeriesPoint(SQLModel):
    day: date
    value: Decimal


class MetricBreakdownEntry(SQLModel):
    key: str
    label: str
    tokens: int = 0
    usd: Decimal = Decimal(0)


class MetricValuePublic(SQLModel):
    """Per-metric envelope in the metrics response."""

    total: Decimal
    delta_vs_prev_window: Decimal | None = None
    series: list[MetricSeriesPoint] = Field(default_factory=list)
    breakdown_by_source: list[MetricBreakdownEntry] | None = None
    top_models: list[MetricBreakdownEntry] | None = None


class MetricsResponse(SQLModel):
    window: Literal["7d", "30d", "all"]
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime
    scope: Literal["personal", "organization"] = "personal"
    is_demo: bool = False
    metrics: dict[str, MetricValuePublic] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class MetricEventRecordedPublic(SQLModel):
    """Response shape for POST /v2/metrics/usage.

    Mirrors the columns the Metrics page can attribute back to a single
    write so the caller (typically a harness hook) can confirm what the
    backend booked. ``usd_amount`` is null when the model_id isn't in
    our pricing snapshot — tokens still record, dollar attribution is
    just deferred until pricing lands."""

    id: uuid.UUID
    kind: str
    occurred_at: datetime
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    usd_amount: str | None = None


# ============================================================
# Taskforce V2 Search — embeddings, BYOK credentials, eligibility
# ============================================================


class SourceItemEmbedding(SQLModel, table=True):
    """One row per indexable chunk across all sources (Documents today,
    Slack/GitHub/Gmail/GDocs later). The ``source_kind`` + ``source_item_id``
    + ``chunk_anchor_id`` triple is unique; re-indexing the same chunk
    replaces the row. ACL columns are denormalized so retrieval can filter
    in SQL without joining the originating table on every query."""

    __tablename__ = "source_item_embedding"
    __table_args__ = (
        UniqueConstraint(
            "source_kind",
            "source_item_id",
            "chunk_anchor_id",
            name="uq_source_item_embedding_anchor",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    source_kind: str = Field(max_length=32, nullable=False)
    source_item_id: str = Field(max_length=64, nullable=False)
    chunk_anchor_id: str = Field(max_length=64, nullable=False)
    chunk_text: str = Field(nullable=False)
    embedding: list[float] = Field(sa_type=Vector(1536))  # type: ignore[arg-type]
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    organization_id: uuid.UUID | None = Field(
        default=None, foreign_key="organization.id", ondelete="SET NULL"
    )
    visibility: str = Field(max_length=16, nullable=False)
    is_demo: bool = Field(default=False, nullable=False)
    # Short hash of the chunk text we embedded. The cron-sweep compares
    # this against the freshly-computed hash before re-embedding, so
    # idempotent re-runs are nearly free.
    version_hash: str = Field(max_length=64, nullable=False)
    indexed_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
        nullable=False,
    )


class ByokCredential(SQLModel, table=True):
    """Bring-Your-Own-Key store for Pro-tier Search.

    The API key itself is Fernet-encrypted at rest (key derived from
    ``settings.BYOK_ENCRYPTION_KEY``). Only the last four characters
    are stored in cleartext (``key_fingerprint``) so the UI can show
    "…sk-Ab9F" without ever reading the ciphertext."""

    __tablename__ = "byok_credential"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_byok_credential_user_provider"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", index=True
    )
    # SQLModel can't infer a SQL column type from a typing.Literal on a
    # table=True model — sqlmodel/main.py:695 calls issubclass(type_, Enum)
    # which raises TypeError on a Literal. Store as plain str here and
    # let the Pydantic Literal validations on ByokCredentialCreate /
    # ByokCredentialPublic enforce the "anthropic"|"openai" constraint
    # at the API boundary.
    provider: str = Field(max_length=32, nullable=False)
    encrypted_api_key: bytes = Field(sa_type=LargeBinary, nullable=False)  # type: ignore[arg-type]
    key_fingerprint: str = Field(max_length=16, nullable=False)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore[arg-type]
        nullable=False,
    )
    last_validated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    revoked_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]


# ---- BYOK request/response shapes ----------------------------


class ByokCredentialCreate(SQLModel):
    provider: Literal["anthropic", "openai"]
    api_key: str = Field(min_length=10, max_length=512)


class ByokCredentialPublic(SQLModel):
    """Returned to the frontend. Never includes the api_key itself."""

    provider: Literal["anthropic", "openai"]
    key_fingerprint: str
    created_at: datetime
    last_validated_at: datetime | None = None
    revoked_at: datetime | None = None


class ByokCredentialsPublic(SQLModel):
    credentials: list[ByokCredentialPublic] = Field(default_factory=list)


# ---- Search eligibility + response shapes --------------------


class SearchEligibilityPublic(SQLModel):
    """Drives the Search tab's gating UX. ``allowed`` is the boolean the
    frontend reads; when ``allowed`` is false, ``reason`` explains how
    the user can become eligible (upgrade vs add BYOK)."""

    tier: Literal["free", "pro", "max"]
    allowed: bool
    route: Literal["managed", "byok:anthropic", "byok:openai"] | None = None
    reason: Literal["upgrade_required", "byok_required"] | None = None
    byok: list[ByokCredentialPublic] = Field(default_factory=list)


class SearchQuery(SQLModel):
    """Request body for POST /v2/search."""

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    demo: bool = False

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import EmailStr
from sqlalchemy import DateTime, UniqueConstraint
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
    is_active: bool = False
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
    is_demo: bool = Field(default=False, index=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]
    updated_at: datetime | None = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )  # type: ignore[arg-type]


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


class V2DocumentFolderCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    visibility: Literal["private", "organization"] = "private"


class V2DocumentFolderUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    visibility: Literal["private", "organization"] | None = None


class V2DocumentFolderPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    organization_id: uuid.UUID | None
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

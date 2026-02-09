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


# --- Tasks/Library/Memory models (demo) ---

LibraryItemKind = Literal["recipe", "pitfall", "decision", "checklist"]
PromotionMode = Literal["auto", "user"]


class LibraryItemBase(SQLModel):
    workflow_key: str = Field(min_length=1)
    # NOTE: keep table-safe primitive types here; constrain via API schemas below.
    # SQLModel's table model creation will choke on `typing.Literal[...]`.
    kind: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body_mdc: str = Field(min_length=1)
    tags: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    source_refs: list[Any] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    promotion_mode: str = "auto"


class LibraryItemCreate(LibraryItemBase):
    kind: LibraryItemKind = Field(min_length=1)
    promotion_mode: PromotionMode = "auto"


class LibraryItemUpdate(SQLModel):
    workflow_key: str | None = Field(default=None, min_length=1)
    kind: LibraryItemKind | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    body_mdc: str | None = Field(default=None, min_length=1)
    tags: dict[str, Any] | None = None
    source_refs: list[Any] | None = None
    promotion_mode: PromotionMode | None = None


class LibraryItem(LibraryItemBase, table=True):
    __tablename__ = "library_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    superseded_by_id: uuid.UUID | None = Field(default=None, foreign_key="library_item.id")


class LibraryItemPublic(LibraryItemBase):
    id: uuid.UUID
    kind: LibraryItemKind
    promotion_mode: PromotionMode
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    superseded_by_id: uuid.UUID | None = None


class LibraryItemsPublic(SQLModel):
    data: list[LibraryItemPublic]
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


# --- Tasks/Runs/Events/Memory link schemas (DB-backed; tables created via scripts) ---

RunLibraryRelation = Literal["used", "created", "promoted", "superseded"]


class TaskPublic(SQLModel):
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


class TaskCreate(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    workflow_key: str = Field(min_length=1)
    intent_key: str | None = Field(default=None, min_length=1)
    goal: str | None = None
    acceptance_criteria: str | None = None
    systems_touched: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(default="read_only", min_length=1)
    status: str = Field(default="open", min_length=1)


class TaskUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    workflow_key: str | None = Field(default=None, min_length=1)
    intent_key: str | None = Field(default=None, min_length=1)
    goal: str | None = None
    acceptance_criteria: str | None = None
    systems_touched: dict[str, Any] | None = None
    risk_level: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1)


class TasksPublic(SQLModel):
    data: list[TaskPublic]
    count: int


class RunPublic(SQLModel):
    id: uuid.UUID
    task_id: uuid.UUID
    targets: list[Any] = Field(default_factory=list, sa_type=JSONB)  # type: ignore[arg-type]
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "aborted"
    summary: str | None = None


class RunCreate(SQLModel):
    targets: list[Any] = Field(default_factory=list)
    status: str = Field(default="running", min_length=1)
    summary: str | None = None


class RunsPublic(SQLModel):
    data: list[RunPublic]
    count: int


class RunUpdate(SQLModel):
    targets: list[Any] | None = None
    ended_at: datetime | None = None
    status: str | None = Field(default=None, min_length=1)
    summary: str | None = None


class RunStartRequest(SQLModel):
    task: TaskCreate
    run: RunCreate = Field(default_factory=RunCreate)
    # If set, reuse the most recently touched Task with the same (workflow_key, intent_key)
    # only if it was touched within this window.
    reuse_within_seconds: int | None = 60 * 60 * 24 * 30


class RunStartPublic(SQLModel):
    task: TaskPublic
    run: RunPublic
    reused_task: bool


class RunEventCreate(SQLModel):
    ts: datetime | None = None
    type: str = Field(min_length=1)
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    supersedes_event_id: int | None = None


class RunEventsPublic(SQLModel):
    data: list["RunEventPublic"]
    count: int


class RunMemoryLinkCreate(SQLModel):
    library_item_id: uuid.UUID
    relation: RunLibraryRelation
    created_at: datetime | None = None


class RunMemoryLinksPublic(SQLModel):
    data: list["RunMemoryLinkPublic"]
    count: int


class RunEventPublic(SQLModel):
    id: int
    run_id: uuid.UUID
    ts: datetime | None = None
    type: str
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict, sa_type=JSONB)  # type: ignore[arg-type]
    supersedes_event_id: int | None = None


class RunMemoryLinkPublic(SQLModel):
    relation: RunLibraryRelation
    created_at: datetime | None = None
    library_item: LibraryItemPublic


class RunDetailPublic(SQLModel):
    run: RunPublic
    events: list[RunEventPublic]
    memory_links: list[RunMemoryLinkPublic]


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


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

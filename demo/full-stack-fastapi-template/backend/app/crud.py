from typing import Any

from sqlmodel import Session, select

from app.core.security import get_password_hash, verify_password
from app.core.tiering import sync_subscription_tier
from app.models import Organization, User, UserCreate, UserUpdate


def _personal_organization_name(user: User) -> str:
    label = user.full_name or user.email
    return f"{label}'s Organization ({str(user.id)[:8]})"


def create_user(
    *, session: Session, user_create: UserCreate, commit: bool = True
) -> User:
    extra_data = {}
    if user_create.password:
        extra_data["hashed_password"] = get_password_hash(user_create.password)
    db_obj = User.model_validate(user_create, update=extra_data)
    sync_subscription_tier(db_obj)
    session.add(db_obj)
    session.flush()
    if db_obj.organization_id is None:
        organization = Organization(name=_personal_organization_name(db_obj))
        session.add(organization)
        session.flush()
        db_obj.organization_id = organization.id
        db_obj.organization_role = "admin"
        session.add(db_obj)
    if commit:
        session.commit()
        session.refresh(db_obj)
    else:
        session.flush()
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    password = user_data.pop("password", None)
    if password:
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    sync_subscription_tier(db_user)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def get_user_by_firebase_uid(*, session: Session, firebase_uid: str) -> User | None:
    statement = select(User).where(User.firebase_uid == firebase_uid)
    session_user = session.exec(statement).first()
    return session_user


DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        verify_password(password, DUMMY_HASH)
        return None
    if not db_user.hashed_password:
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user

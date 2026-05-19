import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import exceptions as firebase_exceptions
from sqlmodel import func, select

from app import crud
from app.api.deps import (
    ActiveUser,
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
    get_current_superuser,
)
from app.core import firebase_auth
from app.core.config import settings
from app.core.demo import ensure_demo_workspace
from app.core.security import get_password_hash, verify_password
from app.models import (
    Message,
    Organization,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.utils import generate_new_account_email, send_email

router = APIRouter(prefix="/users", tags=["users"])


def _validate_organization_id(
    session: SessionDep, organization_id: uuid.UUID | None
) -> None:
    if organization_id is None:
        return
    if not session.get(Organization, organization_id):
        raise HTTPException(status_code=404, detail="Organization not found")


def _validate_organization_role(organization_role: str) -> None:
    if organization_role not in {"admin", "member"}:
        raise HTTPException(status_code=422, detail="Invalid organization role")


def _link_or_create_firebase_user(user: User) -> None:
    if not firebase_auth.firebase_auth_enabled():
        return
    try:
        firebase_user = firebase_auth.ensure_user(
            email=user.email,
            display_name=user.full_name,
        )
    except firebase_auth.FirebaseAuthConfigurationError:
        raise HTTPException(
            status_code=500,
            detail="Firebase authentication is not configured",
        )
    except firebase_exceptions.FirebaseError:
        raise HTTPException(
            status_code=502,
            detail="Could not create Firebase user",
        )
    user.firebase_uid = firebase_user.uid


@router.get(
    "/",
    dependencies=[Depends(get_current_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()
    statement = select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    users = session.exec(statement).all()
    return UsersPublic(data=users, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )
    _validate_organization_id(session, user_in.organization_id)
    _validate_organization_role(user_in.organization_role)

    user = crud.create_user(session=session, user_create=user_in)
    _link_or_create_firebase_user(user)
    if user.firebase_uid:
        session.add(user)
        session.commit()
        session.refresh(user)
    elif settings.emails_enabled and user_in.email and user_in.password:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: ActiveUser
) -> Any:
    if (
        current_user.firebase_uid
        and user_in.email
        and user_in.email != current_user.email
    ):
        raise HTTPException(status_code=400, detail="Email is managed by Firebase")
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: ActiveUser
) -> Any:
    if current_user.firebase_uid:
        raise HTTPException(status_code=400, detail="Password is managed by Firebase")
    if not current_user.hashed_password:
        raise HTTPException(status_code=400, detail="Password is managed by Firebase")
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    return current_user


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: ActiveUser) -> Any:
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    if firebase_auth.firebase_auth_enabled():
        raise HTTPException(
            status_code=400,
            detail="Use Firebase authentication",
        )
    user = crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in)
    user = crud.create_user(session=session, user_create=user_create, commit=False)
    ensure_demo_workspace(session, user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(*, session: SessionDep, user_id: uuid.UUID, user_in: UserUpdate) -> Any:
    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if db_user.firebase_uid and user_in.password:
        raise HTTPException(status_code=400, detail="Password is managed by Firebase")
    if db_user.firebase_uid and user_in.email and user_in.email != db_user.email:
        raise HTTPException(status_code=400, detail="Email is managed by Firebase")
    if user_in.email:
        existing_user = crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    if "organization_id" in user_in.model_fields_set:
        _validate_organization_id(session, user_in.organization_id)
    if "organization_role" in user_in.model_fields_set:
        _validate_organization_role(user_in.organization_role)

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")

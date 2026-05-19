from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_superuser
from app.core import firebase_auth, security
from app.core.config import settings
from app.core.db import is_v2_enabled_identity
from app.core.demo import ensure_demo_workspace
from app.models import (
    FirebaseTokenExchange,
    Message,
    NewPassword,
    Token,
    User,
    UserPublic,
    UserUpdate,
)
from app.utils import (
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_password_reset_token,
)

router = APIRouter(tags=["login"])


def _create_backend_access_token(user: User) -> Token:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


def _exchange_firebase_identity_for_user(
    *,
    session: SessionDep,
    decoded_token: dict[str, Any],
    full_name: str | None,
) -> User:
    firebase_uid = decoded_token.get("uid") or decoded_token.get("sub")
    email = decoded_token.get("email")
    email_verified = bool(decoded_token.get("email_verified", False))

    if not isinstance(firebase_uid, str) or not firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token",
        )
    if not isinstance(email, str) or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Firebase account must include an email address",
        )

    user = crud.get_user_by_firebase_uid(session=session, firebase_uid=firebase_uid)
    if user:
        return user

    user = crud.get_user_by_email(session=session, email=email)
    if user:
        if user.firebase_uid and user.firebase_uid != firebase_uid:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already linked to another Firebase account",
            )
        if not user.firebase_uid and not email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Verify your email before linking this existing account, "
                    "then log in again"
                ),
            )
        user.firebase_uid = firebase_uid
        if full_name and not user.full_name:
            user.full_name = full_name
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    user = User(
        email=email,
        full_name=full_name,
        firebase_uid=firebase_uid,
        is_superuser=False,
        v2=is_v2_enabled_identity(email),
    )
    session.add(user)
    session.flush()
    ensure_demo_workspace(session, user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    if firebase_auth.firebase_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use Firebase authentication",
        )
    user = crud.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    return _create_backend_access_token(user)


@router.post("/login/firebase-token")
def login_firebase_token(session: SessionDep, body: FirebaseTokenExchange) -> Token:
    """
    Exchange a Firebase ID token for the app's backend JWT.
    """
    try:
        decoded_token = firebase_auth.verify_id_token(body.id_token)
    except firebase_auth.FirebaseAuthConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Firebase authentication is not configured",
        )
    except firebase_auth.FirebaseTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase token",
        )

    user = _exchange_firebase_identity_for_user(
        session=session,
        decoded_token=decoded_token,
        full_name=body.full_name,
    )
    return _create_backend_access_token(user)


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    """
    Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    # Always return the same response to prevent email enumeration attacks
    # Only send email if user actually exists
    if user and firebase_auth.firebase_auth_enabled():
        try:
            firebase_user = firebase_auth.get_user_by_email(user.email)
        except firebase_auth.UserNotFoundError:
            firebase_user = firebase_auth.create_user(
                email=user.email,
                display_name=user.full_name,
            )
            user.firebase_uid = firebase_user.uid
            session.add(user)
            session.commit()
        else:
            if not user.firebase_uid and firebase_user.email_verified:
                user.firebase_uid = firebase_user.uid
                session.add(user)
                session.commit()
    elif user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    if firebase_auth.firebase_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is managed by Firebase",
        )
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = crud.get_user_by_email(session=session, email=email)
    if not user:
        # Don't reveal that the user doesn't exist - use same error as invalid token
        raise HTTPException(status_code=400, detail="Invalid token")
    user_in_update = UserUpdate(password=body.new_password)
    crud.update_user(
        session=session,
        db_user=user,
        user_in=user_in_update,
    )
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )

    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )

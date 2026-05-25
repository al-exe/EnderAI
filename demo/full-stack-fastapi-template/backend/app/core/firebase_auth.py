import json
from typing import Any

from firebase_admin import (
    App,
    credentials,
    get_app,
    initialize_app,
)
from firebase_admin import (
    auth as firebase_admin_auth,
)
from firebase_admin import (
    exceptions as firebase_exceptions,
)

from app.core.config import settings


class FirebaseAuthConfigurationError(RuntimeError):
    pass


class FirebaseTokenError(ValueError):
    pass


UserNotFoundError = firebase_admin_auth.UserNotFoundError


def firebase_auth_enabled() -> bool:
    return bool(settings.FIREBASE_PROJECT_ID)


def get_firebase_app() -> App:
    try:
        return get_app()
    except ValueError:
        pass

    if not settings.FIREBASE_PROJECT_ID:
        raise FirebaseAuthConfigurationError("FIREBASE_PROJECT_ID is not configured")

    credential: credentials.Base
    if settings.FIREBASE_SERVICE_ACCOUNT_JSON:
        try:
            service_account_info = json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        except json.JSONDecodeError as exc:
            raise FirebaseAuthConfigurationError(
                "FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON"
            ) from exc
        credential = credentials.Certificate(service_account_info)
    else:
        credential = credentials.ApplicationDefault()

    return initialize_app(
        credential,
        {"projectId": settings.FIREBASE_PROJECT_ID},
    )


def verify_id_token(id_token: str) -> dict[str, Any]:
    try:
        decoded_token = firebase_admin_auth.verify_id_token(
            id_token,
            app=get_firebase_app(),
            check_revoked=True,
        )
    except (
        firebase_admin_auth.CertificateFetchError,
        firebase_admin_auth.ExpiredIdTokenError,
        firebase_admin_auth.InvalidIdTokenError,
        firebase_admin_auth.RevokedIdTokenError,
        firebase_admin_auth.UserDisabledError,
        ValueError,
    ) as exc:
        raise FirebaseTokenError("Invalid Firebase ID token") from exc
    except firebase_exceptions.FirebaseError as exc:
        raise FirebaseTokenError("Could not validate Firebase ID token") from exc
    return decoded_token


def get_user_by_email(email: str) -> Any:
    return firebase_admin_auth.get_user_by_email(email, app=get_firebase_app())


def create_user(email: str, display_name: str | None = None) -> Any:
    kwargs: dict[str, Any] = {"email": email}
    if display_name:
        kwargs["display_name"] = display_name
    return firebase_admin_auth.create_user(app=get_firebase_app(), **kwargs)


def ensure_user(email: str, display_name: str | None = None) -> Any:
    try:
        return get_user_by_email(email)
    except UserNotFoundError:
        return create_user(email=email, display_name=display_name)

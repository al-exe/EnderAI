import random
import string
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings


def session_id_for(label: str) -> str:
    """Deterministic UUID session id for a readable label.

    The fleet/active-session rosters only surface sessions whose id is a real
    (UUID) session id (see ``active_sessions._is_real_session_id``), because the
    backend mints a row for any ``session_id`` that hits ``/observe`` and we do
    not want test/script slug ids to surface. Tests therefore derive a stable
    UUID per readable label instead of using raw slugs.
    """

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tf-test/{label}"))


def random_lower_string() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=32))


def random_email() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"


def get_superuser_token_headers(client: TestClient) -> dict[str, str]:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers

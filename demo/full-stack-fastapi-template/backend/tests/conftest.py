from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    AgentCredential,
    CaseEvent,
    CaseRecord,
    Organization,
    OrganizationInvitation,
    Skill,
    Topic,
    User,
    V2Document,
    V2DocumentFavorite,
    V2DocumentFolder,
    V2DocumentShare,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_migrations() -> None:
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "app/alembic"))
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    _run_migrations()
    with Session(engine) as session:
        init_db(session)
        yield session
        session.execute(delete(CaseEvent))
        session.execute(delete(Skill))
        session.execute(delete(CaseRecord))
        session.execute(delete(Topic))
        session.execute(delete(V2DocumentFavorite))
        session.execute(delete(V2DocumentShare))
        session.execute(delete(V2Document))
        session.execute(delete(V2DocumentFolder))
        session.execute(delete(OrganizationInvitation))
        session.execute(delete(AgentCredential))
        session.execute(delete(User))
        session.execute(delete(Organization))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )

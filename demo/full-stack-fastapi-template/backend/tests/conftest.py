from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Tables holding migration-seeded reference data (e.g. model pricing). Discovered
# once against a freshly-migrated DB and preserved across per-module resets.
_SEEDED_TABLES: set[str] = set()


def _reset_schema() -> None:
    """Drop and recreate the public schema so the suite starts pristine.

    Guarantees ``_discover_seeded_tables`` sees only migration-installed rows,
    not leftovers from a prior run in the shared dev database.
    """
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _run_migrations() -> None:
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "app/alembic"))
    command.upgrade(alembic_cfg, "head")


def _table_names() -> list[str]:
    return [table.name for table in SQLModel.metadata.sorted_tables]


def _discover_seeded_tables(session: Session) -> set[str]:
    """Tables already holding rows on a fresh migration are migration-seeded."""
    seeded: set[str] = set()
    for name in _table_names():
        if name == "alembic_version":
            continue
        has_rows = session.execute(
            text(f'SELECT EXISTS (SELECT 1 FROM "{name}")')
        ).scalar()
        if has_rows:
            seeded.add(name)
    return seeded


def _reset_db(session: Session) -> None:
    """Truncate every non-seeded table and re-seed identity.

    A full cross-test reset that preserves migration-seeded reference tables so
    later modules still see the pricing/reference rows the migrations installed.
    """
    session.rollback()
    targets = [
        f'"{name}"'
        for name in _table_names()
        if name != "alembic_version" and name not in _SEEDED_TABLES
    ]
    if targets:
        session.execute(text(f"TRUNCATE {', '.join(targets)} RESTART IDENTITY CASCADE"))
        session.commit()
    init_db(session)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    _reset_schema()
    _run_migrations()
    with Session(engine) as session:
        _SEEDED_TABLES.clear()
        _SEEDED_TABLES.update(_discover_seeded_tables(session))
        init_db(session)
        yield session
        _reset_db(session)


@pytest.fixture(scope="module", autouse=True)
def _isolate_module(db: Session) -> Generator[None, None, None]:
    """Reset the DB between test modules so cross-file state cannot leak.

    Each module already passes in isolation; resetting per module reproduces that
    clean start without per-test truncation, which would break the module-scoped
    seeded-user fixtures below.
    """
    yield
    _reset_db(db)


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

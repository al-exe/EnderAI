from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))
V2_ENABLED_USER = "alexlee4190"


def is_v2_enabled_identity(identity: str) -> bool:
    normalized = identity.strip().lower()
    return normalized == V2_ENABLED_USER or normalized.startswith(f"{V2_ENABLED_USER}@")


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = crud.create_user(session=session, user_create=user_in, commit=False)
        user.v2 = is_v2_enabled_identity(user.email)
        session.add(user)
        session.commit()
        session.refresh(user)
    elif is_v2_enabled_identity(user.email) and not user.v2:
        user.v2 = True
        session.add(user)
        session.commit()
        session.refresh(user)

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create folders and tables. Swap for Alembic migrations once the schema settles."""
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

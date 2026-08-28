from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import Settings
from data.persistence.models import Base


def make_engine(settings: Settings):
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


def init_db(settings: Settings) -> None:
    """Creates all tables if they don't exist. Safe to call on every startup."""
    engine = make_engine(settings)
    Base.metadata.create_all(engine)


def get_sessionmaker(settings: Settings) -> sessionmaker:
    engine = make_engine(settings)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(settings: Settings):
    SessionLocal = get_sessionmaker(settings)
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Configuración del motor SQLAlchemy y creación de tablas en SQLite."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from adscout.db.orm import Base


def create_db_engine(db_url: str) -> Engine:
    """Crea un Engine de SQLAlchemy configurado para SQLite."""
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    return create_engine(db_url, future=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Devuelve una fábrica de sesiones SQLAlchemy."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Crea las tablas definidas en Base si aún no existen."""
    Base.metadata.create_all(bind=engine)

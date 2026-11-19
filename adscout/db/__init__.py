"""Capa de persistencia SQLite con SQLAlchemy para AdScout."""

from adscout.db.database import create_db_engine, create_session_factory, init_db
from adscout.db.orm import (
    AdAnalysisORM,
    AdORM,
    Base,
    IngestionRunORM,
    LLMUsageLogORM,
    NicheValidationORM,
)
from adscout.db.repository import AdRepository

__all__ = [
    "AdAnalysisORM",
    "AdORM",
    "AdRepository",
    "Base",
    "IngestionRunORM",
    "LLMUsageLogORM",
    "NicheValidationORM",
    "create_db_engine",
    "create_session_factory",
    "init_db",
]

"""Modelos ORM SQLAlchemy para anuncios, corridas, caché LLM y control de gasto."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarativa SQLAlchemy 2.0."""


class AdORM(Base):
    """Tabla principal de anuncios deduplicados por ad_id."""

    __tablename__ = "ads"

    ad_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    page_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    page_name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="und")
    ad_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    headline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cta: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    link_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_domain: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, index=True, nullable=False, default=True)
    platforms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    snapshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    variants_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class IngestionRunORM(Base):
    """Registro histórico de corridas por mercado y fuente de datos."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    total_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class AdAnalysisORM(Base):
    """Caché persistente de análisis semánticos (GeminiProvider) por ad_id."""

    __tablename__ = "ad_analyses"

    ad_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    nicho: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    tipo_producto: Mapped[str] = mapped_column(String(128), nullable=False)
    promesa_principal: Mapped[str] = mapped_column(Text, nullable=False)
    gancho: Mapped[str] = mapped_column(Text, nullable=False)
    publico_objetivo: Mapped[str] = mapped_column(Text, nullable=False)
    resumen_es: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="gemini")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NicheValidationORM(Base):
    """Historial de validaciones de nicho realizadas con PerplexityProvider."""

    __tablename__ = "niche_validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nicho: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(8), index=True, nullable=False)
    tendencia: Mapped[str] = mapped_column(Text, nullable=False)
    saturacion: Mapped[str] = mapped_column(Text, nullable=False)
    competidores_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    resumen_ejecutivo: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="perplexity")
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)


class LLMUsageLogORM(Base):
    """Registro de llamadas a APIs LLM para hacer cumplir el tope diario de gasto."""

    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

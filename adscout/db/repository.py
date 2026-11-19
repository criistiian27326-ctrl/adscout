"""Repositorio de acceso a datos con deduplicación por ad_id y caché LLM."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from adscout.db.orm import (
    AdAnalysisORM,
    AdORM,
    IngestionRunORM,
    LLMUsageLogORM,
    NicheValidationORM,
)
from adscout.models.ad import Ad, utc_now
from adscout.models.llm import AdAnalysisResult, NicheValidationResult

logger = logging.getLogger("adscout.db.repository")


def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _orm_to_ad(row: AdORM) -> Ad:
    try:
        platforms = json.loads(row.platforms_json) if row.platforms_json else []
    except json.JSONDecodeError:
        platforms = []
    try:
        raw_json = json.loads(row.raw_json) if row.raw_json else {}
    except json.JSONDecodeError:
        raw_json = {}

    return Ad(
        ad_id=row.ad_id,
        page_id=row.page_id,
        page_name=row.page_name,
        country=row.country,
        language=row.language,
        ad_text=row.ad_text,
        headline=row.headline,
        cta=row.cta,
        link_url=row.link_url,
        link_domain=row.link_domain,
        start_date=row.start_date,
        end_date=row.end_date,
        is_active=row.is_active,
        platforms=platforms,
        snapshot_url=row.snapshot_url,
        variants_count=row.variants_count,
        raw_json=raw_json,
        first_seen_at=_ensure_utc(row.first_seen_at),
        last_seen_at=_ensure_utc(row.last_seen_at),
    )


class AdRepository:
    """Encapsula todas las operaciones CRUD, deduplicación, caché y cuota LLM."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_ads(
        self,
        ads: list[Ad],
        market_code: str,
        country: str,
        source_name: str,
        run_timestamp: datetime | None = None,
    ) -> dict[str, int]:
        """Inserta anuncios nuevos y actualiza last_seen_at en existentes sin duplicar."""
        now = _ensure_utc(run_timestamp) if run_timestamp else utc_now()

        # Deduplicación dentro del mismo lote por ad_id
        deduped_batch: dict[str, Ad] = {}
        for ad in ads:
            existing_in_batch = deduped_batch.get(ad.ad_id)
            if existing_in_batch is None:
                deduped_batch[ad.ad_id] = ad
            else:
                # Preserva la fecha más antigua de first_seen_at y el mayor variants_count
                merged = ad.model_copy(
                    update={
                        "first_seen_at": min(_ensure_utc(existing_in_batch.first_seen_at), _ensure_utc(ad.first_seen_at)),
                        "last_seen_at": max(_ensure_utc(existing_in_batch.last_seen_at), _ensure_utc(ad.last_seen_at)),
                        "variants_count": max(existing_in_batch.variants_count, ad.variants_count),
                    }
                )
                deduped_batch[ad.ad_id] = merged

        inserted = 0
        updated = 0

        with self._session_factory() as session:
            for ad in deduped_batch.values():
                existing = session.get(AdORM, ad.ad_id)
                if existing is None:
                    first_seen = _ensure_utc(ad.first_seen_at) if ad.first_seen_at else now
                    last_seen = max(_ensure_utc(ad.last_seen_at), first_seen) if ad.last_seen_at else now
                    row = AdORM(
                        ad_id=ad.ad_id,
                        page_id=ad.page_id,
                        page_name=ad.page_name,
                        country=ad.country,
                        language=ad.language,
                        ad_text=ad.ad_text,
                        headline=ad.headline,
                        cta=ad.cta,
                        link_url=ad.link_url,
                        link_domain=ad.link_domain,
                        start_date=ad.start_date,
                        end_date=ad.end_date,
                        is_active=ad.is_active,
                        platforms_json=json.dumps(ad.platforms, ensure_ascii=False),
                        snapshot_url=ad.snapshot_url,
                        variants_count=ad.variants_count,
                        raw_json=json.dumps(ad.raw_json, ensure_ascii=False, default=str),
                        first_seen_at=first_seen,
                        last_seen_at=last_seen,
                    )
                    session.add(row)
                    inserted += 1
                else:
                    # Nunca sobreescribir first_seen_at; solo avanzar last_seen_at
                    existing_last = _ensure_utc(existing.last_seen_at)
                    incoming_last = _ensure_utc(ad.last_seen_at) if ad.last_seen_at else now
                    existing.last_seen_at = max(existing_last, incoming_last, now)

                    existing.page_id = ad.page_id or existing.page_id
                    existing.page_name = ad.page_name or existing.page_name
                    existing.country = ad.country or existing.country
                    existing.language = ad.language or existing.language
                    if ad.ad_text:
                        existing.ad_text = ad.ad_text
                    if ad.headline:
                        existing.headline = ad.headline
                    if ad.cta:
                        existing.cta = ad.cta
                    if ad.link_url:
                        existing.link_url = ad.link_url
                    if ad.link_domain:
                        existing.link_domain = ad.link_domain
                    if ad.start_date:
                        existing.start_date = ad.start_date
                    existing.end_date = ad.end_date
                    existing.is_active = ad.is_active
                    if ad.platforms:
                        existing.platforms_json = json.dumps(ad.platforms, ensure_ascii=False)
                    if ad.snapshot_url:
                        existing.snapshot_url = ad.snapshot_url
                    existing.variants_count = max(existing.variants_count, ad.variants_count)
                    if ad.raw_json:
                        existing.raw_json = json.dumps(ad.raw_json, ensure_ascii=False, default=str)
                    updated += 1

            session.add(
                IngestionRunORM(
                    market_code=market_code,
                    country=country.upper(),
                    source_name=source_name,
                    total_fetched=len(ads),
                    inserted_count=inserted,
                    updated_count=updated,
                    executed_at=now,
                )
            )
            session.commit()

        logger.info(
            "Upsert completado (%s/%s): recibidos=%d, nuevos=%d, actualizados=%d",
            market_code,
            source_name,
            len(ads),
            inserted,
            updated,
        )
        return {
            "total_fetched": len(ads),
            "unique_in_batch": len(deduped_batch),
            "inserted": inserted,
            "updated": updated,
        }

    def list_ads(self, country: str | None = None, only_active: bool = False) -> list[Ad]:
        """Devuelve todos los anuncios filtrados opcionalmente por país y estado."""
        with self._session_factory() as session:
            stmt = select(AdORM)
            if country:
                stmt = stmt.where(AdORM.country == country.upper())
            if only_active:
                stmt = stmt.where(AdORM.is_active.is_(True))
            stmt = stmt.order_by(AdORM.last_seen_at.desc())
            rows = session.scalars(stmt).all()
            return [_orm_to_ad(row) for row in rows]

    def get_ad(self, ad_id: str) -> Ad | None:
        """Obtiene un anuncio por su ad_id."""
        with self._session_factory() as session:
            row = session.get(AdORM, ad_id)
            return _orm_to_ad(row) if row else None

    def list_ads_by_page(self, page_id: str, country: str | None = None) -> list[Ad]:
        """Devuelve todos los anuncios pertenecientes a una misma página."""
        with self._session_factory() as session:
            stmt = select(AdORM).where(AdORM.page_id == page_id)
            if country:
                stmt = stmt.where(AdORM.country == country.upper())
            stmt = stmt.order_by(AdORM.start_date.desc())
            return [_orm_to_ad(row) for row in session.scalars(stmt).all()]

    def count_active_ads_by_page(self, country: str | None = None) -> dict[str, int]:
        """Cuenta cuántos anuncios activos tiene cada page_id en un mercado."""
        with self._session_factory() as session:
            stmt = (
                select(AdORM.page_id, func.count(AdORM.ad_id))
                .where(AdORM.is_active.is_(True))
                .group_by(AdORM.page_id)
            )
            if country:
                stmt = stmt.where(AdORM.country == country.upper())
            return {page_id: int(count) for page_id, count in session.execute(stmt).all()}

    def list_runs(self, market_code: str | None = None, limit: int = 50) -> list[dict]:
        """Devuelve el historial de corridas recientes."""
        with self._session_factory() as session:
            stmt = select(IngestionRunORM)
            if market_code:
                stmt = stmt.where(IngestionRunORM.market_code == market_code)
            stmt = stmt.order_by(IngestionRunORM.executed_at.desc()).limit(limit)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": row.id,
                    "market_code": row.market_code,
                    "country": row.country,
                    "source_name": row.source_name,
                    "total_fetched": row.total_fetched,
                    "inserted_count": row.inserted_count,
                    "updated_count": row.updated_count,
                    "executed_at": _ensure_utc(row.executed_at),
                }
                for row in rows
            ]

    # ------------------------------------------------------------------
    # Caché LLM y control de tope diario de llamadas
    # ------------------------------------------------------------------
    def get_ad_analysis(self, ad_id: str) -> AdAnalysisResult | None:
        with self._session_factory() as session:
            row = session.get(AdAnalysisORM, ad_id)
            if row is None:
                return None
            return AdAnalysisResult(
                nicho=row.nicho,
                tipo_producto=row.tipo_producto,
                promesa_principal=row.promesa_principal,
                gancho=row.gancho,
                publico_objetivo=row.publico_objetivo,
                resumen_es=row.resumen_es,
                provider=row.provider,
                model_name=row.model_name,
                analyzed_at=_ensure_utc(row.analyzed_at),
            )

    def save_ad_analysis(self, ad_id: str, analysis: AdAnalysisResult) -> None:
        with self._session_factory() as session:
            row = session.get(AdAnalysisORM, ad_id)
            if row is None:
                row = AdAnalysisORM(
                    ad_id=ad_id,
                    nicho=analysis.nicho,
                    tipo_producto=analysis.tipo_producto,
                    promesa_principal=analysis.promesa_principal,
                    gancho=analysis.gancho,
                    publico_objetivo=analysis.publico_objetivo,
                    resumen_es=analysis.resumen_es,
                    provider=analysis.provider,
                    model_name=analysis.model_name,
                    analyzed_at=_ensure_utc(analysis.analyzed_at),
                )
                session.add(row)
            else:
                row.nicho = analysis.nicho
                row.tipo_producto = analysis.tipo_producto
                row.promesa_principal = analysis.promesa_principal
                row.gancho = analysis.gancho
                row.publico_objetivo = analysis.publico_objetivo
                row.resumen_es = analysis.resumen_es
                row.provider = analysis.provider
                row.model_name = analysis.model_name
                row.analyzed_at = _ensure_utc(analysis.analyzed_at)
            session.commit()

    def list_all_analyses(self, ad_ids: list[str] | None = None) -> dict[str, AdAnalysisResult]:
        with self._session_factory() as session:
            stmt = select(AdAnalysisORM)
            if ad_ids is not None:
                if not ad_ids:
                    return {}
                stmt = stmt.where(AdAnalysisORM.ad_id.in_(ad_ids))
            rows = session.scalars(stmt).all()
            return {
                row.ad_id: AdAnalysisResult(
                    nicho=row.nicho,
                    tipo_producto=row.tipo_producto,
                    promesa_principal=row.promesa_principal,
                    gancho=row.gancho,
                    publico_objetivo=row.publico_objetivo,
                    resumen_es=row.resumen_es,
                    provider=row.provider,
                    model_name=row.model_name,
                    analyzed_at=_ensure_utc(row.analyzed_at),
                )
                for row in rows
            }

    def save_niche_validation(self, validation: NicheValidationResult) -> None:
        with self._session_factory() as session:
            session.add(
                NicheValidationORM(
                    nicho=validation.nicho,
                    country=validation.country.upper(),
                    tendencia=validation.tendencia,
                    saturacion=validation.saturacion,
                    competidores_json=json.dumps(validation.competidores, ensure_ascii=False),
                    resumen_ejecutivo=validation.resumen_ejecutivo,
                    sources_json=json.dumps(validation.sources, ensure_ascii=False),
                    provider=validation.provider,
                    model_name=validation.model_name,
                    validated_at=_ensure_utc(validation.validated_at),
                )
            )
            session.commit()

    def get_latest_niche_validation(self, nicho: str, country: str) -> NicheValidationResult | None:
        with self._session_factory() as session:
            stmt = (
                select(NicheValidationORM)
                .where(
                    func.lower(NicheValidationORM.nicho) == nicho.strip().lower(),
                    NicheValidationORM.country == country.upper(),
                )
                .order_by(NicheValidationORM.validated_at.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            if row is None:
                return None
            return NicheValidationResult(
                nicho=row.nicho,
                country=row.country,
                tendencia=row.tendencia,
                saturacion=row.saturacion,
                competidores=json.loads(row.competidores_json or "[]"),
                resumen_ejecutivo=row.resumen_ejecutivo,
                sources=json.loads(row.sources_json or "[]"),
                provider=row.provider,
                model_name=row.model_name,
                validated_at=_ensure_utc(row.validated_at),
            )

    def list_niche_validations(self, country: str | None = None) -> list[NicheValidationResult]:
        with self._session_factory() as session:
            stmt = select(NicheValidationORM)
            if country:
                stmt = stmt.where(NicheValidationORM.country == country.upper())
            stmt = stmt.order_by(NicheValidationORM.validated_at.desc())
            rows = session.scalars(stmt).all()
            return [
                NicheValidationResult(
                    nicho=row.nicho,
                    country=row.country,
                    tendencia=row.tendencia,
                    saturacion=row.saturacion,
                    competidores=json.loads(row.competidores_json or "[]"),
                    resumen_ejecutivo=row.resumen_ejecutivo,
                    sources=json.loads(row.sources_json or "[]"),
                    provider=row.provider,
                    model_name=row.model_name,
                    validated_at=_ensure_utc(row.validated_at),
                )
                for row in rows
            ]

    def count_llm_calls_today(self, provider: str | None = None, reference_dt: datetime | None = None) -> int:
        """Cuenta llamadas LLM registradas durante el día UTC actual."""
        ref = _ensure_utc(reference_dt) if reference_dt else utc_now()
        start_of_day = datetime(ref.year, ref.month, ref.day, tzinfo=timezone.utc)
        with self._session_factory() as session:
            stmt = select(func.count(LLMUsageLogORM.id)).where(LLMUsageLogORM.called_at >= start_of_day)
            if provider:
                stmt = stmt.where(LLMUsageLogORM.provider == provider)
            return int(session.scalar(stmt) or 0)

    def record_llm_call(
        self,
        provider: str,
        action: str,
        target_id: str = "",
        called_at: datetime | None = None,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                LLMUsageLogORM(
                    provider=provider,
                    action=action,
                    target_id=target_id,
                    called_at=_ensure_utc(called_at) if called_at else utc_now(),
                )
            )
            session.commit()

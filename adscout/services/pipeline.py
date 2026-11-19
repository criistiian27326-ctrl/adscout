"""Pipeline de ingestión (Fuente -> Normalización -> Deduplicación -> Scoring) y Tendencias."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

from adscout.db.repository import AdRepository
from adscout.models.ad import Ad, domain_matches_checkout
from adscout.models.llm import AdAnalysisResult
from adscout.models.market import MarketConfig
from adscout.models.scoring import ScoreResult
from adscout.scoring.engine import ScoringEngine
from adscout.sources.base import AdSource

logger = logging.getLogger("adscout.services.pipeline")


class IngestionPipeline:
    """Orquesta la búsqueda en una AdSource y la persistencia deduplicada en SQLite."""

    def __init__(self, repository: AdRepository, scoring_engine: ScoringEngine) -> None:
        self.repository = repository
        self.scoring_engine = scoring_engine

    def run(
        self,
        source: AdSource,
        market: MarketConfig,
        keywords: list[str] | None = None,
        limit: int = 100,
        run_timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        """Ejecuta una corrida completa y devuelve métricas de inserción/actualización."""
        effective_keywords = keywords if keywords is not None else market.keywords
        logger.info(
            "Iniciando corrida AdScout | mercado=%s (%s) | fuente=%s | limite=%d",
            market.code,
            market.country,
            source.name,
            limit,
        )
        ads = source.search(market_config=market, keywords=effective_keywords, limit=limit)
        stats = self.repository.upsert_ads(
            ads=ads,
            market_code=market.code,
            country=market.country,
            source_name=source.name,
            run_timestamp=run_timestamp,
        )
        stats["market_code"] = market.code
        stats["source_name"] = source.name
        return stats

    def get_ranked_ads(
        self,
        market: MarketConfig,
        only_active: bool = False,
        reference_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Obtiene anuncios del mercado con puntaje, desglose y análisis LLM (si existe)."""
        ads = self.repository.list_ads(country=market.country, only_active=only_active)
        if not ads:
            return []

        page_counts = self.repository.count_active_ads_by_page(country=market.country)
        scores: dict[str, ScoreResult] = self.scoring_engine.score_batch(
            ads=ads,
            market=market,
            page_active_counts=page_counts,
            reference_date=reference_date,
        )
        analyses: dict[str, AdAnalysisResult] = self.repository.list_all_analyses(
            ad_ids=[ad.ad_id for ad in ads]
        )

        ranked: list[dict[str, Any]] = []
        for ad in ads:
            score_result = scores[ad.ad_id]
            analysis = analyses.get(ad.ad_id)
            matched_checkout = domain_matches_checkout(ad.link_domain, market.checkout_domains)
            ranked.append(
                {
                    "ad": ad,
                    "score": score_result,
                    "analysis": analysis,
                    "days_active": ad.days_active(reference_date=reference_date),
                    "page_active_ads": page_counts.get(ad.page_id, 0),
                    "matched_checkout": matched_checkout,
                    "nicho": analysis.nicho if analysis else _infer_fallback_topic(ad, market),
                }
            )

        ranked.sort(key=lambda item: (item["score"].total_score, item["days_active"]), reverse=True)
        return ranked


def _infer_fallback_topic(ad: Ad, market: MarketConfig) -> str:
    """Etiqueta orientativa basada en keywords cuando aún no se ejecutó análisis LLM."""
    text = f"{ad.ad_text} {ad.headline}".lower()
    for kw in market.keywords:
        if kw.lower() in text:
            return f"Sin analizar (kw: {kw})"
    return "Sin analizar"


def build_trends_dataframe(
    ads: list[Ad],
    analyses: dict[str, AdAnalysisResult],
    market: MarketConfig,
) -> pd.DataFrame:
    """Calcula crecimiento de nichos/temas entre corridas usando first_seen_at.

    Agrupa los anuncios por nicho (de Gemini si existe, o palabra clave detectada como
    respaldo sin API) y compara la mitad/corrida más reciente contra periodos anteriores.
    """
    if not ads:
        return pd.DataFrame(
            columns=[
                "nicho",
                "total_anuncios",
                "nuevos_ultima_corrida",
                "anteriores",
                "crecimiento_pct",
                "anuncios_activos",
                "primera_deteccion",
                "ultima_deteccion",
            ]
        )

    rows: list[dict[str, Any]] = []
    for ad in ads:
        analysis = analyses.get(ad.ad_id)
        nicho = analysis.nicho if analysis else _infer_fallback_topic(ad, market)
        rows.append(
            {
                "ad_id": ad.ad_id,
                "nicho": nicho,
                "first_seen_date": ad.first_seen_at.date(),
                "is_active": ad.is_active,
            }
        )

    df = pd.DataFrame(rows)
    unique_dates = sorted(df["first_seen_date"].unique())
    latest_date = unique_dates[-1]

    summary_rows: list[dict[str, Any]] = []
    for nicho, group in df.groupby("nicho"):
        total = int(len(group))
        newest = int((group["first_seen_date"] == latest_date).sum())
        previous = total - newest
        if previous > 0:
            growth_pct = round((newest / previous) * 100.0, 1)
        else:
            growth_pct = 100.0 if newest > 0 else 0.0

        summary_rows.append(
            {
                "nicho": nicho,
                "total_anuncios": total,
                "nuevos_ultima_corrida": newest,
                "anteriores": previous,
                "crecimiento_pct": growth_pct,
                "anuncios_activos": int(group["is_active"].sum()),
                "primera_deteccion": str(group["first_seen_date"].min()),
                "ultima_deteccion": str(group["first_seen_date"].max()),
            }
        )

    result = pd.DataFrame(summary_rows)
    return result.sort_values(
        by=["nuevos_ultima_corrida", "crecimiento_pct", "total_anuncios"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

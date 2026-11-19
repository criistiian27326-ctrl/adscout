"""Motor de puntuación (0-100) configurable en YAML con desglose completo por anuncio."""

from __future__ import annotations

import unicodedata
from datetime import date

from adscout.models.ad import Ad, domain_matches_checkout
from adscout.models.market import MarketConfig
from adscout.models.scoring import ScoreComponent, ScoreResult, ScoringConfig, TieredRuleConfig


def _fold_text(text: str) -> str:
    """Normaliza acentos y mayúsculas para comparación robusta de palabras clave."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _evaluate_tiers(value: int, rule: TieredRuleConfig) -> float:
    """Evalúa una regla por tramos ordenados de mayor a menor."""
    sorted_tiers = sorted(rule.tiers, key=lambda tier: tier.min_value, reverse=True)
    for tier in sorted_tiers:
        if value >= tier.min_value:
            return min(float(tier.points), float(rule.max_points))
    return 0.0


class ScoringEngine:
    """Calcula un puntaje 0-100 transparente basado únicamente en proxies observables.

    Meta no publica ventas ni gasto publicitario para anuncios comerciales; este motor
    nunca inventa esos datos y muestra siempre la evidencia exacta de cada criterio.
    """

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def score_ad(
        self,
        ad: Ad,
        market: MarketConfig,
        page_active_ads_count: int = 1,
        reference_date: date | None = None,
    ) -> ScoreResult:
        """Calcula puntaje total (0-100) y desglose detallado para un anuncio."""
        weights = self.config.weights
        components: list[ScoreComponent] = []

        # 1. Días activo del anuncio
        days = ad.days_active(reference_date=reference_date)
        days_points = _evaluate_tiers(days, weights.days_active)
        components.append(
            ScoreComponent(
                key="days_active",
                label="Días activo",
                points=days_points,
                max_points=weights.days_active.max_points,
                evidence=f"{days} días activo (inicio: {ad.start_date or 'N/D'})",
            )
        )

        # 2. Cantidad de variantes del mismo anuncio
        variants = max(1, ad.variants_count)
        variants_points = _evaluate_tiers(variants, weights.variants_count)
        components.append(
            ScoreComponent(
                key="variants_count",
                label="Variantes del anuncio",
                points=variants_points,
                max_points=weights.variants_count.max_points,
                evidence=f"{variants} variante(s) detectada(s)",
            )
        )

        # 3. Cantidad de anuncios activos de la misma página
        page_ads = max(0, page_active_ads_count)
        page_points = _evaluate_tiers(page_ads, weights.page_active_ads)
        components.append(
            ScoreComponent(
                key="page_active_ads",
                label="Anuncios activos de la página",
                points=page_points,
                max_points=weights.page_active_ads.max_points,
                evidence=f"{page_ads} anuncio(s) activo(s) de {ad.page_name}",
            )
        )

        # 4. Enlace a un dominio de checkout conocido
        matched_checkout = domain_matches_checkout(ad.link_domain, market.checkout_domains)
        checkout_points = (
            min(weights.checkout_domain.match_points, weights.checkout_domain.max_points)
            if matched_checkout
            else min(weights.checkout_domain.no_match_points, weights.checkout_domain.max_points)
        )
        checkout_evidence = (
            f"Coincide con {matched_checkout} ({ad.link_domain})"
            if matched_checkout
            else f"Sin dominio de checkout conocido ({ad.link_domain or 'sin enlace'})"
        )
        components.append(
            ScoreComponent(
                key="checkout_domain",
                label="Dominio de checkout",
                points=checkout_points,
                max_points=weights.checkout_domain.max_points,
                evidence=checkout_evidence,
            )
        )

        # 5. Coincidencia con palabras clave de producto digital
        searchable_text = _fold_text(f"{ad.ad_text} {ad.headline} {ad.cta} {ad.link_url or ''}")
        matched_keywords: list[str] = []
        for kw in market.keywords:
            if _fold_text(kw) in searchable_text:
                matched_keywords.append(kw)

        capped_matches = min(len(matched_keywords), weights.keyword_match.max_matches)
        keyword_points = min(
            capped_matches * weights.keyword_match.points_per_match,
            weights.keyword_match.max_points,
        )
        keyword_evidence = (
            f"Coincidencias ({len(matched_keywords)}): {', '.join(matched_keywords)}"
            if matched_keywords
            else "Sin coincidencias con palabras clave del mercado"
        )
        components.append(
            ScoreComponent(
                key="keyword_match",
                label="Palabras clave digitales",
                points=keyword_points,
                max_points=weights.keyword_match.max_points,
                evidence=keyword_evidence,
            )
        )

        raw_total = sum(comp.points for comp in components)
        total_score = round(max(0.0, min(100.0, raw_total)), 2)

        return ScoreResult(total_score=total_score, components=components)

    def score_batch(
        self,
        ads: list[Ad],
        market: MarketConfig,
        page_active_counts: dict[str, int] | None = None,
        reference_date: date | None = None,
    ) -> dict[str, ScoreResult]:
        """Puntúa un lote de anuncios calculando automáticamente conteos activos por página si no se pasan."""
        if page_active_counts is None:
            computed_counts: dict[str, int] = {}
            for ad in ads:
                if ad.is_active:
                    computed_counts[ad.page_id] = computed_counts.get(ad.page_id, 0) + 1
            page_active_counts = computed_counts

        return {
            ad.ad_id: self.score_ad(
                ad=ad,
                market=market,
                page_active_ads_count=page_active_counts.get(ad.page_id, 1 if ad.is_active else 0),
                reference_date=reference_date,
            )
            for ad in ads
        }

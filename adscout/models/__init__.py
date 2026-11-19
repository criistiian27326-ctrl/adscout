"""Modelos de dominio Pydantic de AdScout."""

from adscout.models.ad import Ad, domain_matches_checkout, extract_domain, normalize_platforms, parse_date
from adscout.models.llm import AdAnalysisResult, NicheValidationResult
from adscout.models.market import MarketConfig
from adscout.models.scoring import ScoreComponent, ScoreResult, ScoringConfig

__all__ = [
    "Ad",
    "AdAnalysisResult",
    "MarketConfig",
    "NicheValidationResult",
    "ScoreComponent",
    "ScoreResult",
    "ScoringConfig",
    "domain_matches_checkout",
    "extract_domain",
    "normalize_platforms",
    "parse_date",
]

"""Modelos Pydantic para configuración y resultados del motor de puntuación."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreTier(BaseModel):
    """Tramo de puntuación para métricas numéricas (ej. días activo, variantes)."""

    min_value: int = Field(..., ge=0)
    points: float = Field(..., ge=0)


class TieredRuleConfig(BaseModel):
    """Regla basada en tramos ordenados descendentemente."""

    max_points: float = Field(..., ge=0)
    description: str = ""
    tiers: list[ScoreTier] = Field(default_factory=list)


class CheckoutRuleConfig(BaseModel):
    """Regla de coincidencia con dominios de checkout conocidos."""

    max_points: float = Field(..., ge=0)
    description: str = ""
    match_points: float = Field(default=15, ge=0)
    no_match_points: float = Field(default=0, ge=0)


class KeywordRuleConfig(BaseModel):
    """Regla de coincidencia con palabras clave de producto digital."""

    max_points: float = Field(..., ge=0)
    description: str = ""
    points_per_match: float = Field(default=5, ge=0)
    max_matches: int = Field(default=3, ge=1)


class ScoringWeightsConfig(BaseModel):
    """Conjunto de reglas que componen el puntaje 0-100."""

    days_active: TieredRuleConfig
    variants_count: TieredRuleConfig
    page_active_ads: TieredRuleConfig
    checkout_domain: CheckoutRuleConfig
    keyword_match: KeywordRuleConfig


class ScoringConfig(BaseModel):
    """Configuración completa del motor de puntuación cargada desde YAML."""

    weights: ScoringWeightsConfig


class ScoreComponent(BaseModel):
    """Desglose transparente de un criterio individual del puntaje."""

    key: str
    label: str
    points: float = Field(..., ge=0)
    max_points: float = Field(..., ge=0)
    evidence: str


class ScoreResult(BaseModel):
    """Resultado completo de puntuación (0-100) con desglose por criterio."""

    total_score: float = Field(..., ge=0, le=100)
    components: list[ScoreComponent] = Field(default_factory=list)

    def as_dict(self) -> dict[str, ScoreComponent]:
        return {comp.key: comp for comp in self.components}

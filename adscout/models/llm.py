"""Modelos Pydantic para respuestas validadas de proveedores LLM."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field

from adscout.models.ad import utc_now


class AdAnalysisResult(BaseModel):
    """Salida JSON validada de GeminiProvider para un anuncio."""

    nicho: str = Field(..., min_length=1, description="Nicho principal del producto digital")
    tipo_producto: str = Field(..., min_length=1, description="ebook, PDF, curso, plantilla, comunidad Whop, etc.")
    promesa_principal: str = Field(..., min_length=1, description="Promesa central o transformación ofrecida")
    gancho: str = Field(..., min_length=1, description="Gancho o ángulo publicitario principal")
    publico_objetivo: str = Field(..., min_length=1, description="Perfil de audiencia objetivo")
    resumen_es: str = Field(..., min_length=1, description="Resumen conciso en español")
    provider: str = Field(default="gemini")
    model_name: str = Field(default="")
    analyzed_at: datetime = Field(default_factory=utc_now)


class NicheValidationResult(BaseModel):
    """Salida validada de PerplexityProvider al pulsar 'Validar nicho'."""

    nicho: str = Field(..., min_length=1)
    country: str = Field(..., min_length=2, max_length=2)
    tendencia: str = Field(..., min_length=1, description="Análisis de tendencia y demanda actual")
    saturacion: str = Field(..., min_length=1, description="Nivel estimado de saturación y competencia")
    competidores: list[str] = Field(default_factory=list, description="Ejemplos de competidores o referencias")
    resumen_ejecutivo: str = Field(..., min_length=1, description="Conclusión accionable en español")
    sources: list[str] = Field(default_factory=list, description="URLs de fuentes citadas por Perplexity")
    provider: str = Field(default="perplexity")
    model_name: str = Field(default="")
    validated_at: datetime = Field(default_factory=utc_now)

"""Interfaz abstracta AdSource y excepciones tipadas para fuentes de datos."""

from __future__ import annotations

from abc import ABC, abstractmethod

from adscout.models.ad import Ad
from adscout.models.market import MarketConfig


class SourceError(Exception):
    """Error base al consultar o importar desde una fuente de anuncios."""


class SourceConfigError(SourceError):
    """Falta configuración obligatoria en .env o parámetros de la fuente."""


class RateLimitError(SourceError):
    """Límite de tasa alcanzado (por ejemplo, código 613 de Meta Graph API)."""


class InvalidTokenError(SourceError):
    """Token de acceso inválido o expirado (por ejemplo, código 190 de Meta Graph API)."""


class AdSource(ABC):
    """Interfaz obligatoria que toda fuente de anuncios debe implementar."""

    name: str = "base"
    label: str = "Fuente genérica"
    description: str = ""
    is_paid: bool = False

    @abstractmethod
    def search(
        self,
        market_config: MarketConfig,
        keywords: list[str],
        limit: int = 100,
    ) -> list[Ad]:
        """Busca o importa anuncios normalizados para un mercado y palabras clave."""

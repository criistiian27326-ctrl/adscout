"""Fuente Fase 2 (FUENTE DE PAGO OPCIONAL): esqueleto funcional para actores de Apify.

Requiere cuenta de pago o créditos activos en Apify y configurar APIFY_API_TOKEN
y APIFY_ACTOR_ID en el archivo .env.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import quote_plus

import httpx

from adscout.models.ad import Ad
from adscout.models.market import MarketConfig
from adscout.sources.base import (
    AdSource,
    InvalidTokenError,
    RateLimitError,
    SourceConfigError,
    SourceError,
)
from adscout.sources.csv_import import normalize_raw_record

logger = logging.getLogger("adscout.sources.apify")


class ApifySource(AdSource):
    """[FUENTE DE PAGO OPCIONAL] Ejecuta un actor de Apify y normaliza los resultados a Ad."""

    name = "apify"
    label = "Apify Actor Scraper (Fuente de pago opcional)"
    description = (
        "Fuente de pago opcional. Ejecuta un actor de Apify configurado por APIFY_ACTOR_ID "
        "y APIFY_API_TOKEN en .env para recolectar anuncios públicos de la Biblioteca de Meta "
        "en cualquier país y normalizarlos al esquema Ad."
    )
    is_paid = True

    def __init__(
        self,
        api_token: str | None = None,
        actor_id: str = "apify~facebook-ads-scraper",
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
        base_backoff_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_token = (api_token or "").strip()
        self.actor_id = actor_id.strip() or "apify~facebook-ads-scraper"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._transport = transport
        self._sleep = sleep_fn

    def _build_actor_input(self, market_config: MarketConfig, keywords: list[str], limit: int) -> dict[str, Any]:
        """Construye las URLs públicas de búsqueda en Meta Ad Library como entrada del actor."""
        effective_keywords = [kw.strip() for kw in keywords if kw.strip()] or market_config.keywords
        start_urls = [
            {
                "url": (
                    "https://www.facebook.com/ads/library/"
                    f"?active_status=active&ad_type=all&country={market_config.country}"
                    f"&q={quote_plus(kw)}&search_type=keyword_unordered"
                )
            }
            for kw in effective_keywords
        ]
        return {
            "startUrls": start_urls,
            "resultsLimit": limit,
            "country": market_config.country,
            "isDetailsPerAd": True,
        }

    def search(
        self,
        market_config: MarketConfig,
        keywords: list[str],
        limit: int = 100,
    ) -> list[Ad]:
        if not self.api_token:
            raise SourceConfigError(
                "APIFY_API_TOKEN no está configurado en .env. "
                "Apify es una fuente de pago opcional; para costo cero usa CsvImportSource."
            )

        url = f"https://api.apify.com/v2/acts/{self.actor_id}/run-sync-get-dataset-items"
        params = {"token": self.api_token, "clean": "true", "limit": str(limit)}
        actor_input = self._build_actor_input(market_config, keywords, limit)

        logger.info(
            "Ejecutando ApifySource (fuente de pago opcional) | actor=%s | país=%s | limite=%d",
            self.actor_id,
            market_config.country,
            limit,
        )

        items: list[dict[str, Any]] = []
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(url, params=params, json=actor_input)
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        self._sleep(self.base_backoff_seconds * (2**attempt))
                        continue
                    raise SourceError(f"Error de red ejecutando actor de Apify: {exc}") from exc

                if response.status_code in (401, 403):
                    raise InvalidTokenError(
                        "APIFY_API_TOKEN inválido o sin permisos para ejecutar el actor."
                    )

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        self._sleep(self.base_backoff_seconds * (2**attempt))
                        continue
                    if response.status_code == 429:
                        raise RateLimitError("Límite de tasa alcanzado en la API de Apify.")
                    raise SourceError(f"Apify devolvió error HTTP {response.status_code}.")

                if response.status_code >= 400:
                    raise SourceError(
                        f"Error ejecutando actor de Apify (HTTP {response.status_code}): {response.text[:300]}"
                    )

                payload = response.json()
                if not isinstance(payload, list):
                    raise SourceError("La respuesta de Apify no es una lista de ítems del dataset.")
                items = [item for item in payload if isinstance(item, dict)]
                break

        ads: list[Ad] = []
        for idx, record in enumerate(items, start=1):
            try:
                ads.append(normalize_raw_record(record, market_config))
            except ValueError as exc:
                logger.warning("Ítem #%d de Apify omitido por faltar ad_id: %s", idx, exc)
            if len(ads) >= limit:
                break

        logger.info("ApifySource normalizó %d anuncios para %s", len(ads), market_config.country)
        return ads

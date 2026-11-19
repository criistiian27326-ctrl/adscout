"""Fuente Fase 2: Meta Ad Library API Oficial (Graph API /ads_archive).

NOTA LEGAL Y DE COBERTURA:
Meta restringe el acceso vía API a anuncios comerciales ÚNICAMENTE a anuncios
entregados en la Unión Europea (UE) o Reino Unido (UK). En Brasil u otros países
fuera de UE/UK, la API oficial solo devuelve anuncios de temas sociales,
elecciones o política (aunque se pase ad_type=ALL).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import httpx

from adscout.models.ad import Ad, extract_domain, normalize_platforms, parse_date, utc_now
from adscout.models.market import MarketConfig
from adscout.sources.base import (
    AdSource,
    InvalidTokenError,
    RateLimitError,
    SourceConfigError,
    SourceError,
)

logger = logging.getLogger("adscout.sources.meta_official_api")

DEFAULT_FIELDS = ",".join(
    [
        "id",
        "page_id",
        "page_name",
        "ad_creation_time",
        "ad_delivery_start_time",
        "ad_delivery_stop_time",
        "ad_creative_bodies",
        "ad_creative_link_titles",
        "ad_creative_link_captions",
        "ad_creative_link_descriptions",
        "ad_snapshot_url",
        "publisher_platforms",
        "languages",
    ]
)

EU_UK_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE", "GB", "UK",
}


class MetaOfficialApiSource(AdSource):
    """Consulta oficial a https://graph.facebook.com/<version>/ads_archive."""

    name = "meta_official_api"
    label = "Meta Ad Library API Oficial (Gratis — Comercial solo UE/UK)"
    description = (
        "Consulta la Graph API oficial de Meta (/ads_archive) con paginación y backoff. "
        "Aviso: los anuncios comerciales vía API solo están disponibles si se entregaron en UE/UK."
    )
    is_paid = False

    def __init__(
        self,
        access_token: str | None = None,
        api_version: str = "v21.0",
        ad_active_status: str = "ACTIVE",
        ad_type: str = "ALL",
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        base_backoff_seconds: float = 1.5,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.access_token = (access_token or "").strip()
        self.api_version = api_version.strip() or "v21.0"
        self.ad_active_status = ad_active_status.strip().upper() or "ACTIVE"
        self.ad_type = ad_type.strip().upper() or "ALL"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._transport = transport
        self._sleep = sleep_fn

    @property
    def endpoint_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/ads_archive"

    def _request_with_retry(
        self,
        client: httpx.Client,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ejecuta GET con reintentos y backoff exponencial ante error 613 / 429 / 5xx."""
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self.base_backoff_seconds * (2**attempt)
                    logger.warning(
                        "Error de red consultando Meta API (%s). Reintento %d/%d en %.1fs.",
                        exc,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                raise SourceError(f"Error de red al conectar con Meta Graph API: {exc}") from exc

            try:
                payload = response.json()
            except ValueError as exc:
                raise SourceError(
                    f"Respuesta no JSON de Meta Graph API (HTTP {response.status_code})."
                ) from exc

            error_obj = payload.get("error") if isinstance(payload, dict) else None
            if error_obj or response.status_code >= 400:
                code = error_obj.get("code") if isinstance(error_obj, dict) else None
                message = (
                    error_obj.get("message")
                    if isinstance(error_obj, dict)
                    else f"HTTP {response.status_code}"
                )

                # Error 190: token inválido o expirado -> fallo inmediato y claro
                if code == 190 or response.status_code == 401:
                    logger.error("Token de Meta inválido o expirado (código %s): %s", code, message)
                    raise InvalidTokenError(
                        f"Token de Meta inválido o expirado (error {code or 190}): {message}. "
                        "Genera un nuevo META_ACCESS_TOKEN en developers.facebook.com."
                    )

                # Error 613: rate limit -> reintentar con backoff exponencial
                if code == 613 or response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        delay = self.base_backoff_seconds * (2**attempt)
                        logger.warning(
                            "Rate limit / error transitorio Meta API (código=%s, HTTP=%d). "
                            "Reintento %d/%d en %.1fs.",
                            code,
                            response.status_code,
                            attempt + 1,
                            self.max_retries,
                            delay,
                        )
                        self._sleep(delay)
                        continue
                    if code == 613 or response.status_code == 429:
                        raise RateLimitError(
                            f"Límite de llamadas excedido en Meta Graph API (error {code or 613}): {message}"
                        )
                    raise SourceError(f"Meta Graph API devolvió HTTP {response.status_code}: {message}")

                raise SourceError(f"Error de Meta Graph API (código {code}): {message}")

            return payload

        raise SourceError(f"No se pudo completar la solicitud a Meta Graph API: {last_error}")

    def _normalize_item(self, item: dict[str, Any], market_config: MarketConfig) -> Ad | None:
        ad_id = item.get("id")
        if not ad_id:
            return None

        bodies = item.get("ad_creative_bodies") or []
        titles = item.get("ad_creative_link_titles") or []
        captions = item.get("ad_creative_link_captions") or []
        languages = item.get("languages") or []

        ad_text = " ".join(str(b).strip() for b in bodies if b).strip() if isinstance(bodies, list) else str(bodies)
        headline = str(titles[0]).strip() if isinstance(titles, list) and titles else str(titles or "")

        link_candidate = str(captions[0]).strip() if isinstance(captions, list) and captions else None
        link_url = None
        if link_candidate and "." in link_candidate and " " not in link_candidate:
            link_url = link_candidate if "://" in link_candidate else f"https://{link_candidate}"

        start_date = parse_date(item.get("ad_delivery_start_time") or item.get("ad_creation_time"))
        end_date = parse_date(item.get("ad_delivery_stop_time"))
        is_active = end_date is None

        now = utc_now()
        return Ad(
            ad_id=str(ad_id),
            page_id=str(item.get("page_id") or "unknown_page"),
            page_name=str(item.get("page_name") or "Anunciante desconocido"),
            country=market_config.country,
            language=str(languages[0]) if isinstance(languages, list) and languages else market_config.language,
            ad_text=ad_text,
            headline=headline,
            cta="",
            link_url=link_url,
            link_domain=extract_domain(link_url),
            start_date=start_date,
            end_date=end_date,
            is_active=is_active,
            platforms=normalize_platforms(item.get("publisher_platforms")),
            snapshot_url=item.get("ad_snapshot_url") or f"https://www.facebook.com/ads/library/?id={ad_id}",
            variants_count=max(1, len(bodies)) if isinstance(bodies, list) else 1,
            raw_json=item,
            first_seen_at=now,
            last_seen_at=now,
        )

    def search(
        self,
        market_config: MarketConfig,
        keywords: list[str],
        limit: int = 100,
    ) -> list[Ad]:
        if not self.access_token:
            raise SourceConfigError(
                "META_ACCESS_TOKEN no está configurado en .env. "
                "Consulta el README para obtener un token en developers.facebook.com."
            )

        if market_config.country.upper() not in EU_UK_COUNTRIES:
            logger.warning(
                "Aviso: %s (%s) está fuera de UE/UK. La API oficial de Meta solo devuelve "
                "anuncios comerciales entregados en UE/UK; fuera de esa región solo incluye anuncios políticos/sociales.",
                market_config.name,
                market_config.country,
            )

        search_terms_list = [kw.strip() for kw in keywords if kw.strip()] or [""]
        collected: dict[str, Ad] = {}
        page_size = min(max(limit, 1), 100)

        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            for term in search_terms_list:
                if len(collected) >= limit:
                    break

                params: dict[str, Any] = {
                    "access_token": self.access_token,
                    "ad_reached_countries": json.dumps([market_config.country]),
                    "ad_active_status": self.ad_active_status,
                    "ad_type": self.ad_type,
                    "fields": DEFAULT_FIELDS,
                    "limit": page_size,
                }
                if term:
                    params["search_terms"] = term

                next_url: str | None = self.endpoint_url
                next_params: dict[str, Any] | None = params

                while next_url and len(collected) < limit:
                    payload = self._request_with_retry(client, next_url, params=next_params)
                    items = payload.get("data") or []
                    if not isinstance(items, list) or not items:
                        break

                    for raw_item in items:
                        if not isinstance(raw_item, dict):
                            continue
                        ad = self._normalize_item(raw_item, market_config)
                        if ad and ad.ad_id not in collected:
                            collected[ad.ad_id] = ad
                            if len(collected) >= limit:
                                break

                    paging = payload.get("paging") or {}
                    next_url = paging.get("next") if isinstance(paging, dict) else None
                    # paging.next ya incluye cursor y query params
                    next_params = None

        logger.info(
            "MetaOfficialApiSource obtuvo %d anuncios únicos para %s",
            len(collected),
            market_config.country,
        )
        return list(collected.values())

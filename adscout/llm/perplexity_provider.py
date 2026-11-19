"""Proveedor LLM Perplexity (API compatible con OpenAI) para validación bajo demanda de nichos."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from adscout.db.repository import AdRepository
from adscout.llm.base import (
    DailyCallLimiter,
    LLMConfigError,
    LLMError,
    LLMProvider,
    extract_json_object,
)
from adscout.models.llm import NicheValidationResult
from adscout.models.market import MarketConfig

logger = logging.getLogger("adscout.llm.perplexity")

PERPLEXITY_SYSTEM_PROMPT = (
    "Eres un investigador de mercado digital riguroso. Cuando se te consulte un nicho "
    "de productos digitales, evalúa su tendencia actual, saturación y competidores reales "
    "en el país solicitado usando fuentes verificables. Responde en español y devuelve "
    "exclusivamente un objeto JSON válido."
)


class PerplexityProvider(LLMProvider):
    """Consulta bajo demanda ('Validar nicho') usando la API compatible con OpenAI de Perplexity."""

    provider_name = "perplexity"

    def __init__(
        self,
        api_key: str | None,
        model_name: str = "sonar",
        base_url: str = "https://api.perplexity.ai",
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        base_backoff_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model_name = model_name.strip() or "sonar"
        self.base_url = base_url.strip().rstrip("/") or "https://api.perplexity.ai"
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._transport = transport
        self._sleep = sleep_fn

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _extract_sources(self, payload: dict[str, Any]) -> list[str]:
        sources: list[str] = []
        raw_citations = payload.get("citations")
        if isinstance(raw_citations, list):
            for item in raw_citations:
                if isinstance(item, str) and item.strip():
                    sources.append(item.strip())

        search_results = payload.get("search_results")
        if isinstance(search_results, list):
            for entry in search_results:
                if isinstance(entry, dict) and entry.get("url"):
                    url = str(entry["url"]).strip()
                    if url and url not in sources:
                        sources.append(url)
        return sources

    def invoke(
        self,
        prompt: str,
        system_prompt: str = PERPLEXITY_SYSTEM_PROMPT,
    ) -> tuple[str, list[str]]:
        if not self.api_key:
            raise LLMConfigError("PERPLEXITY_API_KEY no está configurada en .env.")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model_name,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }

        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = client.post(url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        self._sleep(self.base_backoff_seconds * (2**attempt))
                        continue
                    raise LLMError(f"Error de red al consultar Perplexity: {exc}") from exc

                if response.status_code in (401, 403):
                    raise LLMConfigError("PERPLEXITY_API_KEY inválida o sin permisos.")

                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        self._sleep(self.base_backoff_seconds * (2**attempt))
                        continue
                    raise LLMError(f"Perplexity devolvió HTTP {response.status_code} tras reintentos.")

                if response.status_code >= 400:
                    raise LLMError(f"Error de Perplexity (HTTP {response.status_code}): {response.text[:300]}")

                payload = response.json()
                choices = payload.get("choices") or []
                if not choices:
                    raise LLMError("Perplexity no devolvió opciones de respuesta.")
                content = choices[0].get("message", {}).get("content", "")
                if not content:
                    raise LLMError("Perplexity devolvió contenido vacío.")

                return str(content), self._extract_sources(payload)

        raise LLMError("No se pudo completar la consulta a Perplexity.")

    def validate_niche(
        self,
        nicho: str,
        market: MarketConfig,
        repository: AdRepository,
        limiter: DailyCallLimiter,
    ) -> NicheValidationResult:
        """Consulta tendencia, saturación y competidores del nicho elegido y muestra fuentes."""
        clean_nicho = nicho.strip()
        if not clean_nicho:
            raise LLMError("Debes indicar un nicho válido para validar.")

        if not self.is_configured():
            raise LLMConfigError(
                "PERPLEXITY_API_KEY no está configurada en .env. Configúrala para usar 'Validar nicho'."
            )

        limiter.assert_within_limit()

        prompt = (
            f"Evalúa el nicho de productos digitales '{clean_nicho}' en el mercado de "
            f"{market.name} ({market.country}, idioma {market.language}).\n"
            "Investiga y devuelve exclusivamente un objeto JSON en español con estas claves:\n"
            "{\n"
            '  "tendencia": "análisis concreto de demanda y tendencia actual",\n'
            '  "saturacion": "nivel estimado de saturación (baja/media/alta) y explicación",\n'
            '  "competidores": ["competidor o referente 1", "competidor 2", "competidor 3"],\n'
            '  "resumen_ejecutivo": "recomendación accionable y ángulos de diferenciación"\n'
            "}"
        )

        raw_text, sources = self.invoke(prompt)
        limiter.record_call(provider=self.provider_name, action="validate_niche", target_id=clean_nicho)

        data = extract_json_object(raw_text)
        data["nicho"] = clean_nicho
        data["country"] = market.country
        data["sources"] = sources
        data["provider"] = self.provider_name
        data["model_name"] = self.model_name

        try:
            result = NicheValidationResult.model_validate(data)
        except ValidationError as exc:
            raise LLMError(f"La respuesta de Perplexity no cumple el esquema esperado: {exc}") from exc

        repository.save_niche_validation(result)
        logger.info("Validación Perplexity guardada para nicho='%s' (%d fuentes)", clean_nicho, len(sources))
        return result

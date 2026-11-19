"""Proveedor LLM Gemini (google-genai) con validación Pydantic y caché en SQLite."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from pydantic import ValidationError

from adscout.db.repository import AdRepository
from adscout.llm.base import (
    DailyCallLimiter,
    LLMConfigError,
    LLMError,
    LLMProvider,
    extract_json_object,
)
from adscout.models.ad import Ad
from adscout.models.llm import AdAnalysisResult
from adscout.models.market import MarketConfig

logger = logging.getLogger("adscout.llm.gemini")

SYSTEM_PROMPT = (
    "Eres un analista experto en investigación de mercado de productos digitales "
    "(ebooks, PDFs, cursos online, plantillas, comunidades Whop). "
    "Responde SIEMPRE en español y exclusivamente con un objeto JSON válido, "
    "sin texto adicional ni explicaciones fuera del JSON."
)


class GeminiProvider(LLMProvider):
    """Analiza anuncios individuales usando el SDK oficial google-genai."""

    provider_name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        model_name: str = "gemini-2.5-flash",
        max_retries: int = 2,
        base_backoff_seconds: float = 1.5,
        client_override: Any = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model_name = model_name.strip() or "gemini-2.5-flash"
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self._client_override = client_override
        self._sleep = sleep_fn

    def is_configured(self) -> bool:
        return bool(self.api_key) or self._client_override is not None

    def _get_client(self) -> Any:
        if self._client_override is not None:
            return self._client_override
        if not self.api_key:
            raise LLMConfigError("GEMINI_API_KEY no está configurada en .env.")
        from google import genai  # Importación diferida para arrancar sin dependencias activas

        return genai.Client(api_key=self.api_key)

    def invoke(self, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> tuple[str, list[str]]:
        client = self._get_client()
        from google.genai import types

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        temperature=0.2,
                    ),
                )
                text = getattr(response, "text", None)
                if not text:
                    raise LLMError("Gemini devolvió una respuesta vacía.")
                return str(text), []
            except LLMError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    delay = self.base_backoff_seconds * (2**attempt)
                    logger.warning(
                        "Error llamando a Gemini (%s). Reintento %d/%d en %.1fs.",
                        exc,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    self._sleep(delay)
                    continue
                raise LLMError(f"Error al consultar Gemini ({self.model_name}): {exc}") from exc

        raise LLMError(f"Error inesperado consultando Gemini: {last_exc}")

    def _build_ad_prompt(self, ad: Ad, market: MarketConfig) -> str:
        return (
            f"Analiza el siguiente anuncio de la Biblioteca de anuncios de Meta en el mercado "
            f"{market.name} ({market.country}, idioma {market.language}).\n\n"
            f"- Página/Anunciante: {ad.page_name}\n"
            f"- Titular: {ad.headline or '(sin titular)'}\n"
            f"- Texto del anuncio: {ad.ad_text or '(sin texto)'}\n"
            f"- CTA: {ad.cta or '(sin CTA)'}\n"
            f"- Dominio destino: {ad.link_domain or '(sin enlace)'}\n"
            f"- Plataformas: {', '.join(ad.platforms) or 'N/D'}\n\n"
            "Devuelve un objeto JSON con exactamente estas claves (todas en español):\n"
            '{\n'
            '  "nicho": "nombre corto y normalizado del nicho (ej. Recetas Fitness, Finanzas Personales)",\n'
            '  "tipo_producto": "ebook | PDF | curso online | plantilla | comunidad Whop | otro",\n'
            '  "promesa_principal": "transformación o beneficio central ofrecido",\n'
            '  "gancho": "gancho o ángulo de atención usado en el copy",\n'
            '  "publico_objetivo": "perfil específico del comprador objetivo",\n'
            '  "resumen_es": "resumen ejecutivo en español de 2-3 frases sin inventar ventas"\n'
            '}'
        )

    def analyze_ad(
        self,
        ad: Ad,
        market: MarketConfig,
        repository: AdRepository,
        limiter: DailyCallLimiter,
        force_refresh: bool = False,
    ) -> tuple[AdAnalysisResult, bool]:
        """Analiza un anuncio validando JSON con Pydantic y cacheando el resultado en SQLite.

        Retorna `(AdAnalysisResult, from_cache)`.
        """
        if not force_refresh:
            cached = repository.get_ad_analysis(ad.ad_id)
            if cached is not None:
                logger.info("Análisis Gemini recuperado de caché SQLite para ad_id=%s", ad.ad_id)
                return cached, True

        if not self.is_configured():
            raise LLMConfigError(
                "GEMINI_API_KEY no está configurada en .env. Configúrala para activar el análisis de anuncios."
            )

        limiter.assert_within_limit()
        raw_text, _ = self.invoke(self._build_ad_prompt(ad, market))
        limiter.record_call(provider=self.provider_name, action="analyze_ad", target_id=ad.ad_id)

        payload = extract_json_object(raw_text)
        payload["provider"] = self.provider_name
        payload["model_name"] = self.model_name

        try:
            result = AdAnalysisResult.model_validate(payload)
        except ValidationError as exc:
            raise LLMError(f"El JSON devuelto por Gemini no cumple el esquema esperado: {exc}") from exc

        repository.save_ad_analysis(ad.ad_id, result)
        logger.info("Análisis Gemini guardado en SQLite para ad_id=%s (nicho=%s)", ad.ad_id, result.nicho)
        return result, False

"""Pruebas de Fase 3: GeminiProvider (validación Pydantic + caché SQLite), PerplexityProvider (fuentes) y tope diario."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from adscout.db.database import create_db_engine, create_session_factory, init_db
from adscout.db.repository import AdRepository
from adscout.llm import (
    DailyCallLimiter,
    GeminiProvider,
    LLMDailyLimitExceededError,
    PerplexityProvider,
)
from adscout.models.ad import Ad
from adscout.models.market import MarketConfig


def _repo() -> AdRepository:
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    return AdRepository(create_session_factory(engine))


def _market() -> MarketConfig:
    return MarketConfig(
        code="brasil",
        name="Brasil",
        country="BR",
        language="pt-BR",
        keywords=["ebook", "PDF"],
        checkout_domains=["hotmart.com"],
    )


def _sample_ad() -> Ad:
    return Ad(
        ad_id="llm_ad_1",
        page_id="pg_1",
        page_name="Receitas Fit BR",
        country="BR",
        language="pt-BR",
        ad_text="Ebook com 120 receitas low carb em PDF",
        headline="Ebook 120 Receitas",
        link_url="https://pay.hotmart.com/X123",
    )


class _FakeGeminiClient:
    def __init__(self, payload_text: str) -> None:
        self.payload_text = payload_text
        self.call_count = 0
        self.models = self

    def generate_content(self, **kwargs):
        self.call_count += 1
        return SimpleNamespace(text=self.payload_text)


def test_gemini_provider_validates_json_and_caches_in_sqlite():
    repo = _repo()
    limiter = DailyCallLimiter(repo, daily_limit=5)

    valid_json = json.dumps(
        {
            "nicho": "Recetas Fitness Low Carb",
            "tipo_producto": "ebook",
            "promesa_principal": "Adelgazar con 120 recetas prácticas en 21 días",
            "gancho": "120 recetas listas sin dietas imposibles",
            "publico_objetivo": "Personas ocupadas buscando alimentación saludable en Brasil",
            "resumen_es": "Ebook en PDF de recetas low carb vendido vía Hotmart orientado a resultados rápidos.",
        }
    )
    fake_client = _FakeGeminiClient(valid_json)
    provider = GeminiProvider(api_key="fake_key", client_override=fake_client)

    ad = _sample_ad()
    market = _market()

    # Primera llamada: invoca Gemini y guarda caché
    result1, from_cache1 = provider.analyze_ad(ad, market, repo, limiter)
    assert from_cache1 is False
    assert fake_client.call_count == 1
    assert result1.nicho == "Recetas Fitness Low Carb"
    assert limiter.used_today() == 1

    # Segunda llamada: usa caché SQLite sin volver a llamar a Gemini ni gastar cuota
    result2, from_cache2 = provider.analyze_ad(ad, market, repo, limiter)
    assert from_cache2 is True
    assert fake_client.call_count == 1
    assert result2.resumen_es == result1.resumen_es
    assert limiter.used_today() == 1


def test_perplexity_provider_validates_niche_and_returns_sources():
    repo = _repo()
    limiter = DailyCallLimiter(repo, daily_limit=5)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "tendencia": "Demanda creciente en micro-plantillas y guías prácticas.",
                                    "saturacion": "Media-alta en recetas genéricas; oportunidad en subnichos.",
                                    "competidores": ["Marca Fit A", "Guía LowCarb B"],
                                    "resumen_ejecutivo": "Conviene diferenciarse con planillas de seguimiento semanal.",
                                }
                            )
                        }
                    }
                ],
                "citations": [
                    "https://trends.google.com/trends/explore?geo=BR",
                    "https://blog.hotmart.com/pt-br/nichos-digitais/",
                ],
            },
        )

    provider = PerplexityProvider(
        api_key="pplx_fake",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
    )

    result = provider.validate_niche("Recetas Fitness Low Carb", _market(), repo, limiter)

    assert result.nicho == "Recetas Fitness Low Carb"
    assert len(result.sources) == 2
    assert "hotmart.com" in result.sources[1]
    assert limiter.used_today() == 1

    saved = repo.get_latest_niche_validation("Recetas Fitness Low Carb", "BR")
    assert saved is not None
    assert saved.sources == result.sources


def test_daily_call_limit_blocks_excess_llm_calls():
    repo = _repo()
    limiter = DailyCallLimiter(repo, daily_limit=1)

    valid_json = json.dumps(
        {
            "nicho": "Finanzas Personales",
            "tipo_producto": "planilha",
            "promesa_principal": "Controlar gastos",
            "gancho": "5 minutos al día",
            "publico_objetivo": "Jóvenes profesionales",
            "resumen_es": "Plantilla financiera.",
        }
    )
    fake_client = _FakeGeminiClient(valid_json)
    provider = GeminiProvider(api_key="fake_key", client_override=fake_client)

    ad1 = _sample_ad()
    ad2 = ad1.model_copy(update={"ad_id": "llm_ad_2"})

    provider.analyze_ad(ad1, _market(), repo, limiter)
    assert limiter.remaining_today() == 0

    with pytest.raises(LLMDailyLimitExceededError):
        provider.analyze_ad(ad2, _market(), repo, limiter)

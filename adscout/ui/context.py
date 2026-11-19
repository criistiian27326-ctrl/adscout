"""Contenedor de dependencias compartidas por las páginas de Streamlit."""

from __future__ import annotations

import os
from dataclasses import dataclass

import streamlit as st

from adscout.config import AppSettings, load_markets, load_scoring_config, load_settings
from adscout.db.database import create_db_engine, create_session_factory, init_db
from adscout.db.repository import AdRepository
from adscout.llm import DailyCallLimiter, GeminiProvider, PerplexityProvider
from adscout.logging_config import configure_logging
from adscout.models.market import MarketConfig
from adscout.scoring.engine import ScoringEngine
from adscout.services.pipeline import IngestionPipeline


@dataclass
class AppContext:
    settings: AppSettings
    markets: dict[str, MarketConfig]
    repository: AdRepository
    scoring_engine: ScoringEngine
    pipeline: IngestionPipeline
    limiter: DailyCallLimiter
    gemini: GeminiProvider
    perplexity: PerplexityProvider


def _sync_streamlit_secrets_to_env() -> None:
    """Copia secretos de Streamlit Community Cloud a os.environ sin sobreescribir valores ya definidos."""
    try:
        secrets = st.secrets
        for key in secrets.keys():
            value = secrets[key]
            if isinstance(value, (str, int, float, bool)) and key not in os.environ:
                os.environ[str(key)] = str(value)
    except Exception:
        # En ejecución local sin .streamlit/secrets.toml es normal que no existan secretos.
        return


def build_app_context() -> AppContext:
    """Inicializa configuración, SQLite, motor de scoring y proveedores LLM opcionales."""
    _sync_streamlit_secrets_to_env()
    settings = load_settings()
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.db_url)
    init_db(engine)
    repository = AdRepository(create_session_factory(engine))

    markets = load_markets(settings.markets_dir)
    scoring_config = load_scoring_config(settings.scoring_config_path)
    scoring_engine = ScoringEngine(scoring_config)
    pipeline = IngestionPipeline(repository=repository, scoring_engine=scoring_engine)

    limiter = DailyCallLimiter(repository=repository, daily_limit=settings.llm_daily_call_limit)
    gemini = GeminiProvider(api_key=settings.gemini_api_key, model_name=settings.gemini_model)
    perplexity = PerplexityProvider(
        api_key=settings.perplexity_api_key,
        model_name=settings.perplexity_model,
        base_url=settings.perplexity_base_url,
    )

    return AppContext(
        settings=settings,
        markets=markets,
        repository=repository,
        scoring_engine=scoring_engine,
        pipeline=pipeline,
        limiter=limiter,
        gemini=gemini,
        perplexity=perplexity,
    )

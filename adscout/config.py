"""Carga de configuración desde .env y archivos YAML (mercados y scoring)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

from adscout.models.market import MarketConfig
from adscout.models.scoring import ScoringConfig

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppSettings:
    """Parámetros de ejecución cargados exclusivamente desde entorno (.env)."""

    db_url: str
    markets_dir: Path
    scoring_config_path: Path
    sample_data_dir: Path
    log_level: str
    # Fase 2: Meta API Oficial
    meta_access_token: str | None
    meta_api_version: str
    meta_ad_type: str
    meta_ad_active_status: str
    meta_timeout_seconds: float
    # Fase 2: Apify (fuente de pago opcional)
    apify_api_token: str | None
    apify_actor_id: str
    apify_timeout_seconds: float
    # Fase 3: LLMs opcionales
    gemini_api_key: str | None
    gemini_model: str
    perplexity_api_key: str | None
    perplexity_model: str
    perplexity_base_url: str
    llm_daily_call_limit: int


def _resolve_path(raw_path: str, base_dir: Path = PROJECT_ROOT) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path).resolve()


def _resolve_db_url(raw_url: str, base_dir: Path = PROJECT_ROOT) -> str:
    """Resuelve rutas relativas de SQLite y crea el directorio padre si no existe."""
    if raw_url.startswith("sqlite:///") and not raw_url.startswith("sqlite:////") and raw_url != "sqlite:///:memory:":
        rel_part = raw_url.removeprefix("sqlite:///")
        abs_path = (base_dir / rel_part).resolve()
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{abs_path}"
    if raw_url.startswith("sqlite:////"):
        abs_path = Path(raw_url.removeprefix("sqlite:///"))
        abs_path.parent.mkdir(parents=True, exist_ok=True)
    return raw_url


def load_settings(env_file: Path | None = None, base_dir: Path = PROJECT_ROOT) -> AppSettings:
    """Carga variables de entorno desde .env (si existe) y devuelve AppSettings."""
    dotenv_path = env_file or (base_dir / ".env")
    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    def _clean_secret(key: str) -> str | None:
        val = os.getenv(key, "").strip()
        return val or None

    raw_db_url = os.getenv("ADSCOUT_DB_URL", "sqlite:///data/adscout.db").strip()

    return AppSettings(
        db_url=_resolve_db_url(raw_db_url, base_dir=base_dir),
        markets_dir=_resolve_path(os.getenv("ADSCOUT_MARKETS_DIR", "markets"), base_dir=base_dir),
        scoring_config_path=_resolve_path(
            os.getenv("ADSCOUT_SCORING_CONFIG", "config/scoring.yaml"),
            base_dir=base_dir,
        ),
        sample_data_dir=_resolve_path(os.getenv("ADSCOUT_SAMPLE_DATA_DIR", "sample_data"), base_dir=base_dir),
        log_level=os.getenv("ADSCOUT_LOG_LEVEL", "INFO").strip().upper(),
        meta_access_token=_clean_secret("META_ACCESS_TOKEN"),
        meta_api_version=os.getenv("META_API_VERSION", "v21.0").strip(),
        meta_ad_type=os.getenv("META_AD_TYPE", "ALL").strip(),
        meta_ad_active_status=os.getenv("META_AD_ACTIVE_STATUS", "ACTIVE").strip(),
        meta_timeout_seconds=float(os.getenv("META_TIMEOUT_SECONDS", "30")),
        apify_api_token=_clean_secret("APIFY_API_TOKEN"),
        apify_actor_id=os.getenv("APIFY_ACTOR_ID", "apify~facebook-ads-scraper").strip(),
        apify_timeout_seconds=float(os.getenv("APIFY_TIMEOUT_SECONDS", "120")),
        gemini_api_key=_clean_secret("GEMINI_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        perplexity_api_key=_clean_secret("PERPLEXITY_API_KEY"),
        perplexity_model=os.getenv("PERPLEXITY_MODEL", "sonar").strip(),
        perplexity_base_url=os.getenv("PERPLEXITY_BASE_URL", "https://api.perplexity.ai").strip().rstrip("/"),
        llm_daily_call_limit=max(0, int(os.getenv("LLM_DAILY_CALL_LIMIT", "25"))),
    )


def load_markets(markets_dir: Path) -> dict[str, MarketConfig]:
    """Descubre y carga todos los mercados definidos en /markets/*.yaml."""
    markets: dict[str, MarketConfig] = {}
    if not markets_dir.exists():
        return markets

    for yaml_path in sorted(markets_dir.glob("*.y*ml")):
        with yaml_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            continue
        raw.setdefault("code", yaml_path.stem.lower())
        raw.setdefault("name", yaml_path.stem.replace("_", " ").title())
        market = MarketConfig.model_validate(raw)
        markets[market.code] = market
    return markets


def load_scoring_config(scoring_config_path: Path) -> ScoringConfig:
    """Carga la configuración de pesos y tramos del motor de puntuación desde YAML."""
    with scoring_config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return ScoringConfig.model_validate(raw)

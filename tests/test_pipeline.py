"""Pruebas de integración del pipeline completo, tendencias e importación de UI."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from adscout.config import load_markets, load_scoring_config
from adscout.db.database import create_db_engine, create_session_factory, init_db
from adscout.db.repository import AdRepository
from adscout.scoring.engine import ScoringEngine
from adscout.services.pipeline import IngestionPipeline, build_trends_dataframe
from adscout.sources.csv_import import CsvImportSource

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_end_to_end_csv_and_apify_json_deduplication_and_trends():
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    repo = AdRepository(create_session_factory(engine))

    market = load_markets(PROJECT_ROOT / "markets")["brasil"]
    scoring = ScoringEngine(load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml"))
    pipeline = IngestionPipeline(repository=repo, scoring_engine=scoring)

    # Corrida 1: CSV de ejemplo (14 anuncios)
    csv_src = CsvImportSource(PROJECT_ROOT / "sample_data" / "brasil_ads_sample.csv")
    stats1 = pipeline.run(
        csv_src,
        market,
        limit=100,
        run_timestamp=datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc),
    )
    assert stats1["inserted"] == 14
    assert stats1["updated"] == 0

    # Corrida 2: JSON de Apify (5 anuncios: 2 existentes br_1001 & br_1007 + 3 nuevos)
    json_src = CsvImportSource(PROJECT_ROOT / "sample_data" / "brasil_ads_apify.json")
    stats2 = pipeline.run(
        json_src,
        market,
        limit=100,
        run_timestamp=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
    )
    assert stats2["inserted"] == 3
    assert stats2["updated"] == 2

    ranked = pipeline.get_ranked_ads(market=market, only_active=False)
    assert len(ranked) == 17
    assert ranked[0]["score"].total_score >= ranked[-1]["score"].total_score

    # Verifica que br_1001 actualizó variants_count de 11 a 14 sin perder first_seen_at
    br_1001 = repo.get_ad("br_1001")
    assert br_1001 is not None
    assert br_1001.variants_count == 14
    assert br_1001.first_seen_at == datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)

    # Verifica cálculo de tendencias usando first_seen_at
    ads = repo.list_ads(country="BR")
    trends_df = build_trends_dataframe(ads=ads, analyses={}, market=market)
    assert not trends_df.empty
    assert "crecimiento_pct" in trends_df.columns
    assert int(trends_df["total_anuncios"].sum()) == 17


def test_streamlit_ui_modules_import_cleanly():
    import app
    from adscout.ui import page_detail, page_market, page_ranking, page_trends

    assert callable(app.main)
    assert callable(page_market.render_market_page)
    assert callable(page_ranking.render_ranking_page)
    assert callable(page_detail.render_detail_page)
    assert callable(page_trends.render_trends_page)

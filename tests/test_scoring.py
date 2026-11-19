"""Pruebas unitarias del motor de puntuación transparente (0-100)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from adscout.config import load_markets, load_scoring_config
from adscout.models.ad import Ad
from adscout.scoring.engine import ScoringEngine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _setup_engine_and_market():
    scoring_cfg = load_scoring_config(PROJECT_ROOT / "config" / "scoring.yaml")
    market = load_markets(PROJECT_ROOT / "markets")["brasil"]
    return ScoringEngine(scoring_cfg), market


def test_high_signal_digital_product_scores_near_100_with_full_breakdown():
    engine, market = _setup_engine_and_market()
    ref_date = date(2026, 11, 19)

    ad = Ad(
        ad_id="high_1",
        page_id="pg_top",
        page_name="Top Infoprodutor",
        country="BR",
        language="pt-BR",
        ad_text="Descubra o ebook em PDF e o guia completo com nosso método exclusivo!",
        headline="Curso online + Planilha",
        cta="Comprar agora",
        link_url="https://pay.hotmart.com/H99999",
        start_date=date(2026, 8, 1),  # 110 días activo (>=90 -> 30 pts)
        is_active=True,
        variants_count=12,  # >=10 -> 20 pts
    )

    result = engine.score_ad(ad, market, page_active_ads_count=16, reference_date=ref_date)

    assert result.total_score == 100.0
    breakdown = result.as_dict()
    assert breakdown["days_active"].points == 30.0
    assert breakdown["variants_count"].points == 20.0
    assert breakdown["page_active_ads"].points == 20.0
    assert breakdown["checkout_domain"].points == 15.0
    assert breakdown["keyword_match"].points == 15.0
    assert "hotmart.com" in breakdown["checkout_domain"].evidence


def test_low_signal_non_checkout_ad_scores_low():
    engine, market = _setup_engine_and_market()
    ref_date = date(2026, 11, 19)

    ad = Ad(
        ad_id="low_1",
        page_id="pg_blog",
        page_name="Blog Genérico",
        country="BR",
        language="pt-BR",
        ad_text="Leia nossa notícia semanal sobre esportes.",
        headline="Notícias de hoje",
        cta="Saiba mais",
        link_url="https://noticiasgenericas.com.br/post",
        start_date=date(2026, 11, 19),  # 0 días activo -> 0 pts
        is_active=True,
        variants_count=1,  # 2 pts
    )

    result = engine.score_ad(ad, market, page_active_ads_count=1, reference_date=ref_date)

    assert 0.0 <= result.total_score <= 10.0
    breakdown = result.as_dict()
    assert breakdown["checkout_domain"].points == 0.0
    assert breakdown["keyword_match"].points == 0.0
    assert breakdown["days_active"].points == 0.0


def test_inactive_ad_uses_end_date_for_days_active():
    engine, market = _setup_engine_and_market()
    ref_date = date(2026, 11, 19)

    ad = Ad(
        ad_id="inactive_1",
        page_id="pg_old",
        page_name="Antigo",
        country="BR",
        ad_text="Ebook rápido",
        link_url="https://whop.com/demo",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 6),  # Solo 5 días activo aunque hoy sea noviembre
        is_active=False,
        variants_count=1,
    )

    result = engine.score_ad(ad, market, page_active_ads_count=0, reference_date=ref_date)
    breakdown = result.as_dict()
    assert ad.days_active(reference_date=ref_date) == 5
    assert breakdown["days_active"].points == 4.0  # tramo >=3 y <7
    assert breakdown["checkout_domain"].points == 15.0  # whop.com

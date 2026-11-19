"""Pruebas unitarias de normalización de anuncios (Ad y CsvImportSource)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from adscout.config import load_markets
from adscout.models.ad import Ad, domain_matches_checkout, extract_domain, normalize_platforms
from adscout.sources.csv_import import CsvImportSource, normalize_raw_record

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _brasil_market():
    return load_markets(PROJECT_ROOT / "markets")["brasil"]


def test_extract_domain_and_checkout_matching():
    assert extract_domain("https://www.pay.hotmart.com/X123?off=1") == "pay.hotmart.com"
    assert extract_domain("kiwify.com.br/checkout/123") == "kiwify.com.br"
    assert extract_domain("  ") is None

    domains = ["hotmart.com", "kiwify.com.br", "whop.com"]
    assert domain_matches_checkout("pay.hotmart.com", domains) == "hotmart.com"
    assert domain_matches_checkout("whop.com", domains) == "whop.com"
    assert domain_matches_checkout("fakehotmart.com", domains) is None


def test_normalize_platforms_handles_multiple_formats():
    assert normalize_platforms("Facebook, INSTAGRAM ; facebook") == ["facebook", "instagram"]
    assert normalize_platforms('["INSTAGRAM", "Audience_Network"]') == ["instagram", "audience_network"]
    assert normalize_platforms(["FACEBOOK", "instagram"]) == ["facebook", "instagram"]
    assert normalize_platforms(None) == []


def test_normalize_apify_nested_record_and_strip_pii():
    market = _brasil_market()
    raw = {
        "adArchiveID": "999001",
        "pageID": "pg_99",
        "pageName": "Loja Digital",
        "startDate": 1756684800,  # 2025-09-01 UTC
        "isActive": "true",
        "publisherPlatform": ["FACEBOOK", "INSTAGRAM"],
        "collationCount": 7,
        "user_email": "private@example.com",
        "phone": "+5511999999999",
        "snapshot": {
            "body": {"text": "Baixe nosso ebook em PDF"},
            "title": "Ebook Completo",
            "cta_text": "Comprar agora",
            "link_url": "https://checkout.kiwify.com.br/abc",
        },
    }

    ad = normalize_raw_record(raw, market)

    assert ad.ad_id == "999001"
    assert ad.page_id == "pg_99"
    assert ad.country == "BR"
    assert ad.language == "pt-BR"
    assert ad.ad_text == "Baixe nosso ebook em PDF"
    assert ad.headline == "Ebook Completo"
    assert ad.cta == "Comprar agora"
    assert ad.link_domain == "checkout.kiwify.com.br"
    assert ad.start_date == date(2025, 9, 1)
    assert ad.is_active is True
    assert ad.platforms == ["facebook", "instagram"]
    assert ad.variants_count == 7
    assert ad.snapshot_url == "https://www.facebook.com/ads/library/?id=999001"
    # Verifica que no se almacenen datos personales en raw_json
    assert "user_email" not in ad.raw_json
    assert "phone" not in ad.raw_json


def test_csv_import_source_reads_csv_and_apify_json():
    market = _brasil_market()

    csv_source = CsvImportSource(PROJECT_ROOT / "sample_data" / "brasil_ads_sample.csv")
    csv_ads = csv_source.search(market, market.keywords, limit=50)
    assert len(csv_ads) == 14
    assert all(isinstance(ad, Ad) for ad in csv_ads)
    assert csv_ads[0].link_domain == "pay.hotmart.com"

    json_source = CsvImportSource(PROJECT_ROOT / "sample_data" / "brasil_ads_apify.json")
    json_ads = json_source.search(market, market.keywords, limit=50)
    assert len(json_ads) == 5
    assert json_ads[0].ad_id == "br_1001"
    assert json_ads[0].variants_count == 14

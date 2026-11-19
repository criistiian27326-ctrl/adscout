"""Pruebas de Fase 2: MetaOfficialApiSource (paginación, 613, 190), ApifySource y SOURCE_REGISTRY."""

from __future__ import annotations

import httpx
import pytest

from adscout.models.ad import Ad
from adscout.models.market import MarketConfig
from adscout.sources import (
    AdSource,
    ApifySource,
    InvalidTokenError,
    MetaOfficialApiSource,
    RateLimitError,
    SOURCE_REGISTRY,
    get_source,
    register_source,
)


def _eu_market() -> MarketConfig:
    return MarketConfig(
        code="espana",
        name="España",
        country="ES",
        language="es-ES",
        keywords=["ebook"],
        checkout_domains=["hotmart.com"],
    )


def test_meta_official_api_pagination_and_normalization():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "after=cursor_2" not in str(request.url):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "meta_1",
                            "page_id": "p1",
                            "page_name": "Academia Digital ES",
                            "ad_delivery_start_time": "2026-09-01",
                            "ad_creative_bodies": ["Descarga nuestro ebook en PDF"],
                            "ad_creative_link_titles": ["Ebook Marketing"],
                            "ad_creative_link_captions": ["pay.hotmart.com"],
                            "publisher_platforms": ["facebook", "instagram"],
                            "ad_snapshot_url": "https://www.facebook.com/ads/library/?id=meta_1",
                        }
                    ],
                    "paging": {
                        "next": "https://graph.facebook.com/v21.0/ads_archive?after=cursor_2"
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "meta_2",
                        "page_id": "p2",
                        "page_name": "Plantillas Pro",
                        "ad_delivery_start_time": "2026-10-01",
                        "ad_creative_bodies": ["Guía completa PDF"],
                        "ad_creative_link_titles": ["Guía PDF"],
                        "ad_creative_link_captions": ["gumroad.com"],
                        "publisher_platforms": ["instagram"],
                    }
                ]
            },
        )

    source = MetaOfficialApiSource(
        access_token="valid_token",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
    )
    ads = source.search(_eu_market(), ["ebook"], limit=10)

    assert len(calls) == 2
    assert [ad.ad_id for ad in ads] == ["meta_1", "meta_2"]
    assert ads[0].link_domain == "pay.hotmart.com"
    assert ads[1].link_domain == "gumroad.com"


def test_meta_official_api_retries_on_error_613_with_backoff():
    attempts = {"count": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(
                400,
                json={"error": {"message": "Calls to this api have exceeded the rate limit.", "code": 613}},
            )
        return httpx.Response(
            200,
            json={"data": [{"id": "meta_ok", "page_id": "p1", "page_name": "OK"}]},
        )

    source = MetaOfficialApiSource(
        access_token="token",
        max_retries=3,
        base_backoff_seconds=1.0,
        transport=httpx.MockTransport(handler),
        sleep_fn=sleeps.append,
    )
    ads = source.search(_eu_market(), ["ebook"], limit=5)

    assert len(ads) == 1
    assert ads[0].ad_id == "meta_ok"
    assert sleeps == [1.0, 2.0]  # Backoff exponencial


def test_meta_official_api_raises_rate_limit_when_613_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Rate limit", "code": 613}})

    source = MetaOfficialApiSource(
        access_token="token",
        max_retries=1,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(RateLimitError):
        source.search(_eu_market(), ["ebook"], limit=5)


def test_meta_official_api_raises_invalid_token_immediately_on_error_190():
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}})

    source = MetaOfficialApiSource(
        access_token="expired_token",
        max_retries=3,
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(InvalidTokenError):
        source.search(_eu_market(), ["ebook"], limit=5)

    assert attempts["count"] == 1  # No reintenta un token inválido


def test_apify_source_marked_paid_and_normalizes_dataset_items():
    assert ApifySource.is_paid is True

    def handler(request: httpx.Request) -> httpx.Response:
        assert "run-sync-get-dataset-items" in str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "adArchiveID": "apify_777",
                    "pageID": "pg_apify",
                    "pageName": "Whop Club BR",
                    "startDate": "2026-10-05",
                    "isActive": True,
                    "collationCount": 4,
                    "snapshot": {
                        "body": {"text": "Comunidade exclusiva no Whop"},
                        "title": "Comunidade Whop",
                        "link_url": "https://whop.com/club-br",
                    },
                }
            ],
        )

    source = ApifySource(
        api_token="apify_secret_test",
        transport=httpx.MockTransport(handler),
        sleep_fn=lambda _: None,
    )
    ads = source.search(_eu_market(), ["whop"], limit=10)

    assert len(ads) == 1
    assert ads[0].ad_id == "apify_777"
    assert ads[0].link_domain == "whop.com"
    assert ads[0].variants_count == 4


def test_registry_allows_adding_custom_source_with_single_registration():
    class CustomDummySource(AdSource):
        name = "custom_dummy"
        label = "Custom Dummy"
        is_paid = True

        def search(self, market_config: MarketConfig, keywords: list[str], limit: int = 10) -> list[Ad]:
            return []

    register_source("custom_dummy", CustomDummySource)
    try:
        instance = get_source("custom_dummy")
        assert isinstance(instance, CustomDummySource)
    finally:
        SOURCE_REGISTRY.pop("custom_dummy", None)

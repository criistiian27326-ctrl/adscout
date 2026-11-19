"""Pruebas unitarias de deduplicación por ad_id y actualización de last_seen_at."""

from __future__ import annotations

from datetime import datetime, timezone

from adscout.db.database import create_db_engine, create_session_factory, init_db
from adscout.db.repository import AdRepository
from adscout.models.ad import Ad


def _build_in_memory_repo() -> AdRepository:
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    return AdRepository(create_session_factory(engine))


def test_deduplication_updates_last_seen_without_duplicating_or_changing_first_seen():
    repo = _build_in_memory_repo()

    t1 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 15, 18, 30, tzinfo=timezone.utc)

    ad_run1 = Ad(
        ad_id="ad_dup_001",
        page_id="pg_1",
        page_name="Produto Digital BR",
        country="BR",
        language="pt-BR",
        ad_text="Ebook completo em PDF",
        link_url="https://pay.hotmart.com/123",
        variants_count=3,
        is_active=True,
        first_seen_at=t1,
        last_seen_at=t1,
    )
    stats1 = repo.upsert_ads([ad_run1], market_code="brasil", country="BR", source_name="csv_import", run_timestamp=t1)
    assert stats1["inserted"] == 1
    assert stats1["updated"] == 0

    # Segunda corrida con el mismo ad_id, más variantes y nuevo timestamp
    ad_run2 = Ad(
        ad_id="ad_dup_001",
        page_id="pg_1",
        page_name="Produto Digital BR",
        country="BR",
        language="pt-BR",
        ad_text="Ebook completo em PDF",
        link_url="https://pay.hotmart.com/123",
        variants_count=9,
        is_active=True,
        first_seen_at=t2,
        last_seen_at=t2,
    )
    stats2 = repo.upsert_ads([ad_run2], market_code="brasil", country="BR", source_name="csv_import", run_timestamp=t2)
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 1

    all_ads = repo.list_ads(country="BR")
    assert len(all_ads) == 1

    stored = all_ads[0]
    assert stored.ad_id == "ad_dup_001"
    assert stored.first_seen_at == t1  # Preservado intacto
    assert stored.last_seen_at == t2   # Actualizado en la segunda corrida
    assert stored.variants_count == 9  # Actualizado al mayor valor


def test_deduplication_within_same_batch():
    repo = _build_in_memory_repo()
    t1 = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)

    dup_a = Ad(
        ad_id="same_batch_1",
        page_id="pg_2",
        page_name="Page 2",
        country="BR",
        variants_count=2,
        first_seen_at=t1,
        last_seen_at=t1,
    )
    dup_b = Ad(
        ad_id="same_batch_1",
        page_id="pg_2",
        page_name="Page 2",
        country="BR",
        variants_count=6,
        first_seen_at=t2,
        last_seen_at=t2,
    )

    stats = repo.upsert_ads([dup_a, dup_b], market_code="brasil", country="BR", source_name="csv_import", run_timestamp=t2)
    assert stats["total_fetched"] == 2
    assert stats["unique_in_batch"] == 1
    assert stats["inserted"] == 1

    stored = repo.get_ad("same_batch_1")
    assert stored is not None
    assert stored.first_seen_at == t1
    assert stored.variants_count == 6

"""Fuente por defecto (Fase 1): importación desde CSV o JSON (manual o Apify)."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

from adscout.models.ad import Ad, extract_domain, normalize_platforms, parse_date, parse_datetime, utc_now
from adscout.models.market import MarketConfig
from adscout.sources.base import AdSource, SourceConfigError, SourceError

logger = logging.getLogger("adscout.sources.csv_import")


def _pick_first(record: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    """Devuelve el primer valor no vacío entre varias posibles claves de origen."""
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def _nested_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    snap = record.get("snapshot")
    return snap if isinstance(snap, dict) else {}


def _extract_body_text(record: dict[str, Any], snap: dict[str, Any]) -> str:
    body = _pick_first(record, ("ad_text", "ad_creative_body", "body", "text", "adText", "copy"))
    if isinstance(body, dict):
        body = body.get("text") or body.get("markup", {}).get("__html", "")
    if isinstance(body, list):
        body = " ".join(str(x) for x in body if x)
    if not body and snap:
        snap_body = snap.get("body")
        if isinstance(snap_body, dict):
            body = snap_body.get("text") or ""
        elif isinstance(snap_body, str):
            body = snap_body
    return str(body or "").strip()


def _extract_headline(record: dict[str, Any], snap: dict[str, Any]) -> str:
    headline = _pick_first(
        record,
        ("headline", "ad_creative_link_title", "title", "link_title", "linkTitle"),
    )
    if isinstance(headline, list):
        headline = headline[0] if headline else ""
    if not headline and snap:
        headline = snap.get("title") or ""
        if not headline and isinstance(snap.get("cards"), list) and snap["cards"]:
            first_card = snap["cards"][0]
            if isinstance(first_card, dict):
                headline = first_card.get("title") or ""
    return str(headline or "").strip()


def _extract_link_url(record: dict[str, Any], snap: dict[str, Any]) -> str | None:
    url = _pick_first(
        record,
        ("link_url", "linkUrl", "url", "landing_page_url", "ad_creative_link_caption", "cta_link"),
    )
    if not url and snap:
        url = snap.get("link_url") or snap.get("linkUrl")
        if not url and isinstance(snap.get("cards"), list) and snap["cards"]:
            first_card = snap["cards"][0]
            if isinstance(first_card, dict):
                url = first_card.get("link_url") or first_card.get("linkUrl")
    if isinstance(url, list):
        url = url[0] if url else None
    return str(url).strip() if url else None


def normalize_raw_record(record: dict[str, Any], market_config: MarketConfig) -> Ad:
    """Normaliza un registro crudo (CSV manual, JSON propio o exportación Apify) a Ad."""
    snap = _nested_snapshot(record)

    ad_id = _pick_first(
        record,
        ("ad_id", "adArchiveID", "ad_archive_id", "archive_id", "id", "library_id"),
    )
    if not ad_id:
        raise ValueError("El registro no contiene un identificador de anuncio (ad_id / adArchiveID / id).")

    page_id = _pick_first(record, ("page_id", "pageID", "pageId")) or snap.get("page_id") or "unknown_page"
    page_name = (
        _pick_first(record, ("page_name", "pageName", "advertiser", "page"))
        or snap.get("page_name")
        or "Anunciante desconocido"
    )

    country = _pick_first(record, ("country", "country_code", "reached_country")) or market_config.country
    if isinstance(country, list):
        country = country[0] if country else market_config.country

    language = _pick_first(record, ("language", "lang", "languages")) or market_config.language
    if isinstance(language, list):
        language = language[0] if language else market_config.language

    ad_text = _extract_body_text(record, snap)
    headline = _extract_headline(record, snap)
    cta = (
        _pick_first(record, ("cta", "cta_text", "ctaText", "call_to_action"))
        or snap.get("cta_text")
        or ""
    )

    link_url = _extract_link_url(record, snap)
    link_domain = _pick_first(record, ("link_domain", "domain")) or extract_domain(link_url)

    start_date = parse_date(
        _pick_first(
            record,
            ("start_date", "startDate", "startDateFormatted", "ad_delivery_start_time", "ad_creation_time"),
        )
    )
    end_date = parse_date(
        _pick_first(
            record,
            ("end_date", "endDate", "endDateFormatted", "ad_delivery_stop_time"),
        )
    )

    raw_active = _pick_first(record, ("is_active", "isActive", "active"))
    if raw_active is None:
        raw_active = end_date is None

    platforms = normalize_platforms(
        _pick_first(
            record,
            ("platforms", "publisher_platforms", "publisherPlatform", "publisherPlatforms"),
        )
    )

    snapshot_url = _pick_first(
        record,
        ("snapshot_url", "ad_snapshot_url", "adSnapshotUrl", "snapshotUrl", "url_snapshot"),
    ) or f"https://www.facebook.com/ads/library/?id={ad_id}"

    variants_count = _pick_first(
        record,
        ("variants_count", "collationCount", "collation_count", "variants", "creative_variants"),
        default=1,
    )

    now = utc_now()
    first_seen_at = parse_datetime(_pick_first(record, ("first_seen_at", "firstSeenAt"))) or now
    last_seen_at = parse_datetime(_pick_first(record, ("last_seen_at", "lastSeenAt"))) or now

    return Ad(
        ad_id=str(ad_id),
        page_id=str(page_id),
        page_name=str(page_name),
        country=str(country)[:2],
        language=str(language),
        ad_text=ad_text,
        headline=headline,
        cta=str(cta or ""),
        link_url=link_url,
        link_domain=link_domain,
        start_date=start_date,
        end_date=end_date,
        is_active=raw_active,
        platforms=platforms,
        snapshot_url=snapshot_url,
        variants_count=variants_count,
        raw_json=record,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )


class CsvImportSource(AdSource):
    """Importa anuncios desde archivos CSV o JSON exportados manualmente o desde Apify."""

    name = "csv_import"
    label = "Importar CSV / JSON (Costo cero - Por defecto)"
    description = (
        "Carga archivos CSV o JSON exportados manualmente desde la Biblioteca de anuncios "
        "o descargados desde un actor de Apify. No requiere ninguna API ni clave."
    )
    is_paid = False

    def __init__(self, file_path: str | Path | None = None, filter_by_keywords: bool = False) -> None:
        self.file_path = Path(file_path) if file_path else None
        self.filter_by_keywords = filter_by_keywords

    def _load_records(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise SourceConfigError(f"El archivo de importación no existe: {path}")

        suffix = path.suffix.lower()
        try:
            if suffix == ".csv":
                with path.open("r", encoding="utf-8-sig", newline="") as fh:
                    reader = csv.DictReader(fh)
                    return [dict(row) for row in reader]
            if suffix == ".json":
                with path.open("r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
                if isinstance(data, dict):
                    for wrapper_key in ("data", "items", "ads", "results"):
                        if isinstance(data.get(wrapper_key), list):
                            return [item for item in data[wrapper_key] if isinstance(item, dict)]
                    return [data]
                raise SourceError(f"Formato JSON no soportado en {path.name}: se esperaba lista u objeto.")
        except (OSError, json.JSONDecodeError, csv.Error) as exc:
            raise SourceError(f"No se pudo leer el archivo {path.name}: {exc}") from exc

        raise SourceError(f"Extensión no soportada '{suffix}'. Usa archivos .csv o .json.")

    def search(
        self,
        market_config: MarketConfig,
        keywords: list[str],
        limit: int = 100,
    ) -> list[Ad]:
        if self.file_path is None:
            raise SourceConfigError("Debes indicar un archivo CSV o JSON para CsvImportSource.")

        records = self._load_records(self.file_path)
        logger.info("Leyendo %d registros crudos desde %s", len(records), self.file_path.name)

        lower_keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
        ads: list[Ad] = []

        for idx, record in enumerate(records, start=1):
            try:
                ad = normalize_raw_record(record, market_config)
            except ValueError as exc:
                logger.warning("Registro #%d omitido en %s: %s", idx, self.file_path.name, exc)
                continue

            if self.filter_by_keywords and lower_keywords:
                haystack = f"{ad.ad_text} {ad.headline} {ad.cta} {ad.link_url or ''}".lower()
                if not any(kw in haystack for kw in lower_keywords):
                    continue

            ads.append(ad)
            if limit > 0 and len(ads) >= limit:
                break

        logger.info("Importados %d anuncios normalizados desde %s", len(ads), self.file_path.name)
        return ads

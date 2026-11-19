"""Capa de fuentes de datos de AdScout."""

from adscout.sources.apify_source import ApifySource
from adscout.sources.base import (
    AdSource,
    InvalidTokenError,
    RateLimitError,
    SourceConfigError,
    SourceError,
)
from adscout.sources.csv_import import CsvImportSource, normalize_raw_record
from adscout.sources.meta_official_api import MetaOfficialApiSource
from adscout.sources.registry import (
    SOURCE_REGISTRY,
    get_source,
    list_registered_sources,
    register_source,
)

__all__ = [
    "AdSource",
    "ApifySource",
    "CsvImportSource",
    "InvalidTokenError",
    "MetaOfficialApiSource",
    "RateLimitError",
    "SOURCE_REGISTRY",
    "SourceConfigError",
    "SourceError",
    "get_source",
    "list_registered_sources",
    "normalize_raw_record",
    "register_source",
]

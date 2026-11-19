"""Registro central de fuentes de datos (diccionario de proveedores).

Para agregar una fuente nueva:
1. Crea un archivo nuevo en `adscout/sources/<tu_fuente>.py` heredando de `AdSource`.
2. Regístrala aquí en `SOURCE_REGISTRY`.
"""

from __future__ import annotations

from typing import Any

from adscout.sources.apify_source import ApifySource
from adscout.sources.base import AdSource
from adscout.sources.csv_import import CsvImportSource
from adscout.sources.meta_official_api import MetaOfficialApiSource

# Diccionario extensible de proveedores de anuncios.
# Agregar una fuente nueva requiere solo un archivo nuevo y añadirla aquí.
SOURCE_REGISTRY: dict[str, type[AdSource]] = {
    "csv_import": CsvImportSource,
    "meta_official_api": MetaOfficialApiSource,
    "apify": ApifySource,
}


def register_source(key: str, source_cls: type[AdSource]) -> None:
    """Registra dinámicamente una nueva clase AdSource en el diccionario."""
    if not issubclass(source_cls, AdSource):
        raise TypeError(f"{source_cls!r} debe heredar de AdSource.")
    SOURCE_REGISTRY[key] = source_cls


def list_registered_sources() -> list[dict[str, Any]]:
    """Devuelve metadatos de todas las fuentes registradas para la UI y CLI."""
    return [
        {
            "key": key,
            "label": cls.label,
            "description": cls.description,
            "is_paid": cls.is_paid,
        }
        for key, cls in SOURCE_REGISTRY.items()
    ]


def get_source(key: str, **kwargs: Any) -> AdSource:
    """Instancia una fuente registrada por clave."""
    if key not in SOURCE_REGISTRY:
        available = ", ".join(SOURCE_REGISTRY.keys())
        raise KeyError(f"Fuente desconocida '{key}'. Disponibles: {available}")
    return SOURCE_REGISTRY[key](**kwargs)

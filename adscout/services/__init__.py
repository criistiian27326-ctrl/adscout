"""Servicios de orquestación del pipeline de ingestión y análisis de tendencias."""

from adscout.services.pipeline import IngestionPipeline, build_trends_dataframe

__all__ = ["IngestionPipeline", "build_trends_dataframe"]

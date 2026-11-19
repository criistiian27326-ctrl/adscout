"""Modelo de configuración de mercado cargado desde /markets/<codigo>.yaml."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class MarketConfig(BaseModel):
    """Define un mercado objetivo (país, idioma, keywords y dominios de checkout)."""

    code: str = Field(..., min_length=1, description="Identificador único del archivo YAML (ej. brasil)")
    name: str = Field(..., min_length=1, description="Nombre legible del mercado (ej. Brasil)")
    country: str = Field(..., min_length=2, max_length=2, description="Código ISO-3166-1 alpha-2 (ej. BR)")
    language: str = Field(..., min_length=2, description="Código de idioma BCP-47 (ej. pt-BR)")
    keywords: list[str] = Field(default_factory=list, description="Palabras clave de producto digital")
    checkout_domains: list[str] = Field(default_factory=list, description="Dominios de checkout conocidos")

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text.lower() not in seen:
                seen.add(text.lower())
                cleaned.append(text)
        return cleaned

    @field_validator("checkout_domains", mode="before")
    @classmethod
    def clean_domains(cls, value: list[str] | None) -> list[str]:
        if not value:
            return []
        seen: set[str] = set()
        cleaned: list[str] = []
        for item in value:
            domain = str(item).strip().lower().removeprefix("http://").removeprefix("https://")
            domain = domain.split("/")[0].removeprefix("www.")
            if domain and domain not in seen:
                seen.add(domain)
                cleaned.append(domain)
        return cleaned

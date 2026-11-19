"""Modelo normalizado Ad y utilidades de normalización y privacidad."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

# Campos personales que nunca deben almacenarse en raw_json
_PII_KEYS = {
    "email",
    "user_email",
    "phone",
    "phone_number",
    "mobile",
    "ip",
    "ip_address",
    "user_id",
    "personal_email",
}


def utc_now() -> datetime:
    """Devuelve datetime UTC actual sin microsegundos."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def extract_domain(url: str | None) -> str | None:
    """Extrae el dominio normalizado (sin www ni puerto) desde una URL."""
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def domain_matches_checkout(link_domain: str | None, checkout_domains: list[str]) -> str | None:
    """Retorna el dominio de checkout coincidente (exacto o subdominio) o None."""
    if not link_domain:
        return None
    normalized_link = link_domain.strip().lower().removeprefix("www.")
    for checkout in checkout_domains:
        target = checkout.strip().lower().removeprefix("www.")
        if not target:
            continue
        if normalized_link == target or normalized_link.endswith(f".{target}"):
            return target
    return None


def normalize_platforms(value: Any) -> list[str]:
    """Normaliza plataformas de publicación desde lista, JSON o cadena delimitada."""
    if value is None:
        return []
    items: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    items = [str(p) for p in parsed]
                else:
                    items = [text]
            except json.JSONDecodeError:
                items = [part for part in text.replace(";", ",").split(",")]
        else:
            items = [part for part in text.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        items = [str(p) for p in value]
    else:
        items = [str(value)]

    seen: set[str] = set()
    normalized: list[str] = []
    for item in items:
        clean = item.strip().lower()
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized


def parse_date(value: Any) -> date | None:
    """Convierte múltiples representaciones de fecha (ISO, epoch, datetime) a date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # Soporta epoch en segundos o milisegundos
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan", "n/a"}:
        return None
    if text.isdigit():
        return parse_date(int(text))

    # ISO-8601 con sufijo Z
    iso_candidate = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: Any) -> datetime | None:
    """Convierte cadenas ISO o timestamps a datetime con zona horaria UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        parsed = parse_date(text)
        if parsed:
            return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
        return None


def sanitize_raw_json(data: Any) -> dict[str, Any]:
    """Elimina posibles claves de datos personales antes de persistir raw_json."""
    if data is None:
        return {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {"raw_text": data}
    if not isinstance(data, dict):
        return {"value": data}

    def _clean(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                str(k): _clean(v)
                for k, v in obj.items()
                if str(k).strip().lower() not in _PII_KEYS
            }
        if isinstance(obj, list):
            return [_clean(item) for item in obj]
        return obj

    return _clean(data)


class Ad(BaseModel):
    """Modelo normalizado de un anuncio procedente de cualquier fuente AdSource."""

    ad_id: str = Field(..., min_length=1)
    page_id: str = Field(default="unknown_page")
    page_name: str = Field(default="Anunciante desconocido")
    country: str = Field(..., min_length=2, max_length=2)
    language: str = Field(default="und")
    ad_text: str = Field(default="")
    headline: str = Field(default="")
    cta: str = Field(default="")
    link_url: str | None = Field(default=None)
    link_domain: str | None = Field(default=None)
    start_date: date | None = Field(default=None)
    end_date: date | None = Field(default=None)
    is_active: bool = Field(default=True)
    platforms: list[str] = Field(default_factory=list)
    snapshot_url: str | None = Field(default=None)
    variants_count: int = Field(default=1, ge=1)
    raw_json: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)

    @field_validator("ad_id", "page_id", "page_name", "language", mode="before")
    @classmethod
    def strip_required_strings(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("country", mode="before")
    @classmethod
    def normalize_country_code(cls, value: Any) -> str:
        return str(value or "").strip().upper()

    @field_validator("ad_text", "headline", "cta", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Any) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return "" if text.lower() in {"nan", "none"} else text

    @field_validator("link_url", "snapshot_url", mode="before")
    @classmethod
    def clean_optional_url(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        return text

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_dates(cls, value: Any) -> date | None:
        return parse_date(value)

    @field_validator("first_seen_at", "last_seen_at", mode="before")
    @classmethod
    def validate_timestamps(cls, value: Any) -> datetime:
        parsed = parse_datetime(value)
        return parsed if parsed is not None else utc_now()

    @field_validator("platforms", mode="before")
    @classmethod
    def validate_platforms(cls, value: Any) -> list[str]:
        return normalize_platforms(value)

    @field_validator("is_active", mode="before")
    @classmethod
    def validate_is_active(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return True
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "si", "sí", "active", "ativo"}:
            return True
        if text in {"false", "0", "no", "inactive", "inativo"}:
            return False
        return True

    @field_validator("variants_count", mode="before")
    @classmethod
    def validate_variants_count(cls, value: Any) -> int:
        if value is None or value == "":
            return 1
        try:
            parsed = int(float(value))
            return max(1, parsed)
        except (TypeError, ValueError):
            return 1

    @field_validator("raw_json", mode="before")
    @classmethod
    def validate_raw_json(cls, value: Any) -> dict[str, Any]:
        return sanitize_raw_json(value)

    @model_validator(mode="after")
    def finalize_fields(self) -> "Ad":
        if not self.page_id:
            self.page_id = "unknown_page"
        if not self.page_name:
            self.page_name = "Anunciante desconocido"
        if not self.link_domain and self.link_url:
            self.link_domain = extract_domain(self.link_url)
        elif self.link_domain:
            self.link_domain = extract_domain(self.link_domain)
        if not self.snapshot_url and self.ad_id:
            self.snapshot_url = f"https://www.facebook.com/ads/library/?id={self.ad_id}"
        if self.end_date is not None and self.start_date is not None and self.end_date < self.start_date:
            self.end_date = self.start_date
        return self

    def days_active(self, reference_date: date | None = None) -> int:
        """Calcula los días activos del anuncio respecto a end_date o reference_date."""
        if self.start_date is None:
            return 0
        ref = reference_date or datetime.now(timezone.utc).date()
        end_ref = self.end_date if (not self.is_active and self.end_date is not None) else ref
        delta = (end_ref - self.start_date).days
        return max(0, delta)

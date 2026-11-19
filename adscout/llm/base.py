"""Interfaz abstracta LLMProvider y control de tope diario de llamadas."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from adscout.db.repository import AdRepository


class LLMError(Exception):
    """Error base al invocar un proveedor LLM."""


class LLMConfigError(LLMError):
    """Falta API key o configuración obligatoria del proveedor LLM."""


class LLMDailyLimitExceededError(LLMError):
    """Se alcanzó el límite diario de llamadas LLM configurado en .env."""


class DailyCallLimiter:
    """Hace cumplir el tope diario de llamadas LLM usando el registro en SQLite."""

    def __init__(self, repository: AdRepository, daily_limit: int) -> None:
        self.repository = repository
        self.daily_limit = max(0, daily_limit)

    def used_today(self, provider: str | None = None) -> int:
        return self.repository.count_llm_calls_today(provider=provider)

    def remaining_today(self) -> int:
        return max(0, self.daily_limit - self.used_today())

    def assert_within_limit(self) -> None:
        used = self.used_today()
        if used >= self.daily_limit:
            raise LLMDailyLimitExceededError(
                f"Tope diario de gasto alcanzado ({used}/{self.daily_limit} llamadas LLM hoy). "
                "Ajusta LLM_DAILY_CALL_LIMIT en .env si deseas aumentarlo."
            )

    def record_call(self, provider: str, action: str, target_id: str = "") -> None:
        self.repository.record_llm_call(provider=provider, action=action, target_id=target_id)


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """Extrae y decodifica un objeto JSON incluso si viene envuelto en bloque Markdown."""
    cleaned = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"La respuesta del modelo no contiene JSON válido: {exc}") from exc

    if not isinstance(parsed, dict):
        raise LLMError("Se esperaba un objeto JSON en la respuesta del proveedor LLM.")
    return parsed


class LLMProvider(ABC):
    """Interfaz abstracta para proveedores LLM opcionales (Gemini, Perplexity, etc.)."""

    provider_name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        """Indica si el proveedor tiene sus credenciales configuradas."""

    @abstractmethod
    def invoke(self, prompt: str, system_prompt: str = "") -> tuple[str, list[str]]:
        """Ejecuta una llamada remota y devuelve (texto_respuesta, lista_de_fuentes)."""

"""Módulo LLM opcional con interfaz LLMProvider, caché SQLite y tope diario de gasto."""

from adscout.llm.base import (
    DailyCallLimiter,
    LLMConfigError,
    LLMDailyLimitExceededError,
    LLMError,
    LLMProvider,
)
from adscout.llm.gemini_provider import GeminiProvider
from adscout.llm.perplexity_provider import PerplexityProvider

__all__ = [
    "DailyCallLimiter",
    "GeminiProvider",
    "LLMConfigError",
    "LLMDailyLimitExceededError",
    "LLMError",
    "LLMProvider",
    "PerplexityProvider",
]

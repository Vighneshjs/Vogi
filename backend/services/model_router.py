from __future__ import annotations

import time
from typing import Any

from ..config import Settings
from ..exceptions import ModelProviderError
from ..integrations.ollama import OllamaClient
from ..integrations.openai import OpenAIClient


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ollama = OllamaClient(settings)
        self.openai = OpenAIClient(settings)
        self._fallback_model: str | None = None
        self._fallback_until = 0.0

    async def list_models(self) -> list[str]:
        ollama_models = []
        try:
            ollama_models = await self.ollama.list_models()
        except Exception:
            ollama_models = ["gemma3:1b", "gemma4:e4b"]
            
        if "gemma3:1b" not in ollama_models:
            ollama_models.append("gemma3:1b")
            
        openai_models = ["gpt-5-mini"]
        
        base = []
        if self.settings.model_provider == "openai":
            base.extend(openai_models)
            base.extend(ollama_models)
        else:
            base.extend(ollama_models)
            base.extend(openai_models)
            
        seen: set[str] = set()
        return [m for m in base if m not in seen and not seen.add(m)]  # type: ignore[func-returns-value]

    async def chat(self, messages: list[dict[str, Any]], *, model: str | None = None, response_format: str | None = None, num_predict: int = 900, temperature: float = 0.15, timeout: int = 180) -> dict[str, Any]:
        selected_model = model or self.settings.agent_model
        if self.settings.model_provider == "openai":
            if self._fallback_model and time.monotonic() < self._fallback_until:
                return await self.chat_with_local_fallback(
                    messages,
                    selected_model,
                    self._fallback_model,
                    response_format,
                    num_predict,
                    temperature,
                    timeout,
                    "Cloud fallback is active after a recent transient provider failure.",
                )
            try:
                return await self.openai.chat(messages, model=selected_model, num_predict=num_predict, temperature=temperature, timeout=min(timeout, 30), response_format=response_format)
            except ModelProviderError as exc:
                if not self.is_transient_cloud_failure(str(exc)):
                    raise
                fallback = await self.local_fallback_model()
                if not fallback:
                    raise
                self._fallback_model = fallback
                self._fallback_until = time.monotonic() + 300
                return await self.chat_with_local_fallback(
                    messages,
                    selected_model,
                    fallback,
                    response_format,
                    num_predict,
                    temperature,
                    timeout,
                    "The cloud model was temporarily unavailable or rate limited.",
                )
        return await self.ollama.chat(messages, model=selected_model, response_format=response_format, num_predict=num_predict, temperature=temperature, timeout=timeout)

    async def chat_with_local_fallback(self, messages: list[dict[str, Any]], selected_model: str, fallback: str, response_format: str | None, num_predict: int, temperature: float, timeout: int, reason: str) -> dict[str, Any]:
        result = await self.ollama.chat(messages, model=fallback, response_format=response_format, num_predict=num_predict, temperature=temperature, timeout=timeout)
        result["fallback"] = {
            "fromProvider": "openai",
            "fromModel": selected_model,
            "provider": "ollama",
            "model": fallback,
            "reason": reason,
        }
        return result

    async def local_fallback_model(self) -> str | None:
        try:
            installed = await self.ollama.list_models()
        except ModelProviderError:
            return None
        for candidate in ("gemma4:e4b", "gemma4:latest", "gemma3:1b"):
            if candidate in installed:
                return candidate
        return None

    @staticmethod
    def is_transient_cloud_failure(error: str) -> bool:
        text = error.lower()
        return any(marker in text for marker in ("http 429", "too many requests", "rate limit", "timeout", "timed out", "http 503", "service unavailable"))

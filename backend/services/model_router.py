from __future__ import annotations

from typing import Any

from ..config import Settings
from ..integrations.ollama import OllamaClient
from ..integrations.openai import OpenAIClient


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ollama = OllamaClient(settings)
        self.openai = OpenAIClient(settings)

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
            return await self.openai.chat(messages, model=selected_model, num_predict=num_predict, temperature=temperature, timeout=timeout, response_format=response_format)
        return await self.ollama.chat(messages, model=selected_model, response_format=response_format, num_predict=num_predict, temperature=temperature, timeout=timeout)

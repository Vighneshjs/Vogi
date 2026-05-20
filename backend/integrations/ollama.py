from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..exceptions import ModelProviderError


class OllamaClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f"{self.settings.ollama_url}/api/tags")
                response.raise_for_status()
        except Exception as exc:
            raise ModelProviderError(str(exc)) from exc
        return [item.get("name") or item.get("model") for item in response.json().get("models", []) if item.get("name") or item.get("model")]

    async def chat(self, messages: list[dict[str, Any]], *, model: str, response_format: str | None = None, num_predict: int = 900, temperature: float = 0.15, timeout: int = 180) -> dict[str, Any]:
        payload = {
            "model": model,
            "stream": False,
            "think": False,
            "format": response_format,
            "keep_alive": "10m",
            "options": {
                "num_gpu": self.settings.gpu_layers,
                "num_predict": num_predict,
                "temperature": temperature,
            },
            "messages": messages,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{self.settings.ollama_url}/api/chat", json={k: v for k, v in payload.items() if v is not None})
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            raise ModelProviderError(str(exc)) from exc


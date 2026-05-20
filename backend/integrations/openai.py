from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..exceptions import ModelProviderError

# Models that use max_completion_tokens instead of max_tokens
_MAX_COMPLETION_MODELS = {"gpt-5-mini", "gpt-4o", "o1", "o1-mini", "o3", "o3-mini", "o4-mini"}


def _uses_completion_tokens(model: str) -> bool:
    return any(m in model.lower() for m in {"gpt-5", "o1", "o3", "o4"})


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def chat(self, messages: list[dict[str, Any]], *, model: str, num_predict: int = 900, temperature: float = 0.15, timeout: int = 180, response_format: str | None = None) -> dict[str, Any]:
        if not self.settings.openai_api_key:
            raise ModelProviderError("OPENAI_API_KEY is not configured.")

        is_azure = "azure.com" in self.settings.openai_api_base

        # gpt-5 and o-series models require max_completion_tokens, NOT max_tokens
        token_key = "max_completion_tokens" if _uses_completion_tokens(model) else "max_tokens"

        payload: dict[str, Any] = {
            "messages": messages,
            token_key: num_predict,
        }

        # Force JSON output mode when requested (helps models stick to JSON schema)
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        # temperature is not supported / only supports default=1 for gpt-5 and o-series models
        no_temp_models = {"o1", "o3", "o4", "gpt-5"}
        if not any(m in model.lower() for m in no_temp_models):
            payload["temperature"] = temperature

        if is_azure:
            url = f"{self.settings.openai_api_base.rstrip('/')}/openai/deployments/{model}/chat/completions?api-version=2024-12-01-preview"
            headers = {"api-key": self.settings.openai_api_key, "Content-Type": "application/json"}
        else:
            payload["model"] = model
            url = f"{self.settings.openai_api_base.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {self.settings.openai_api_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return {"message": {"content": data["choices"][0]["message"]["content"]}, "raw": data}
        except httpx.HTTPStatusError as exc:
            raise ModelProviderError(f"HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except Exception as exc:
            raise ModelProviderError(str(exc)) from exc

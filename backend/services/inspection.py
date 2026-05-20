from __future__ import annotations

import json
from typing import Any

from ..config import Settings
from .model_router import ModelRouter


SYSTEM_PROMPT = """You are a zero-tolerance Chief HSE Compliance Officer. Inspect images for safety violations and return strict JSON:
{"inspection_status":"PASS|FAIL","critical_threat_detected":false,"severity_level":"CRITICAL|HIGH|MEDIUM|LOW|NONE","detected_violations":[],"violation_marks":[{"image_index":0,"label":"short label","violation":"specific visible violation","bbox":{"x":0,"y":0,"width":0,"height":0}}],"observations":"objective visual evidence","immediate_corrective_actions":[]}
Use normalized bounding boxes from 0 to 1. If no visible violation exists, return PASS, NONE, and empty arrays."""


class InspectionService:
    def __init__(self, settings: Settings, models: ModelRouter) -> None:
        self.settings = settings
        self.models = models

    async def inspect(self, images: list[str]) -> dict[str, Any]:
        data = await self.models.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "Execute safety inspection on the provided visual evidence.", "images": images}],
            model=self.settings.inspection_model,
            response_format="json",
            num_predict=700,
            temperature=0,
        )
        content = data.get("message", {}).get("content", "")
        try:
            inspection = json.loads(content)
        except Exception:
            inspection = {
                "inspection_status": "FAIL",
                "critical_threat_detected": True,
                "severity_level": "HIGH",
                "detected_violations": ["Model returned invalid JSON."],
                "violation_marks": [],
                "observations": content,
                "immediate_corrective_actions": ["Retry with a clearer image or restart the model."],
            }
        return {"inspection": inspection, "raw": data}


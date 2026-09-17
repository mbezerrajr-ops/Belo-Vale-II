from __future__ import annotations

import json
import urllib.request
from functools import lru_cache

from app.core.config import get_settings
from app.vision.contracts import VisionExtraction, VisionLine, VisionProvider


class FakeVisionProvider:
    """Deterministic provider for tests and local development."""

    def extract(self, image_bytes: bytes) -> VisionExtraction:
        return VisionExtraction(
            header_text="LOTE 1 - 22/07/2026",
            lot="1",
            measured_on="22/07/2026",
            header_confidence={"lot": 0.95, "measured_on": 0.95},
            lines=[
                VisionLine(
                    animal_brinco="497",
                    animal_number="497",
                    animal_name="PONTA CURTA",
                    morning="10",
                    afternoon="8",
                    total="18",
                    notes=None,
                    confidence={"morning": 0.98, "afternoon": 0.97, "total": 0.96},
                    bounding_boxes={"total": (0, 0, 10, 10)},
                )
            ],
            provider_name="fake",
            model_name="fake-v1",
        )


class HttpVisionProvider:
    """Adapter over a server-configured HTTP vision/OCR endpoint.

    Never accepts a key from the caller; the key and URL come only from
    server-side Settings, so the frontend can never see or supply them.
    """

    def __init__(self, *, api_url: str, api_key: str, model_name: str) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._model_name = model_name

    def extract(self, image_bytes: bytes) -> VisionExtraction:
        request = urllib.request.Request(
            self._api_url,
            data=image_bytes,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
        return VisionExtraction(
            header_text=payload.get("header_text"),
            lot=payload.get("lot"),
            measured_on=payload.get("measured_on"),
            header_confidence=payload.get("header_confidence", {}),
            lines=[
                VisionLine(
                    animal_brinco=line.get("animal_brinco"),
                    animal_number=line.get("animal_number"),
                    animal_name=line.get("animal_name"),
                    morning=line.get("morning"),
                    afternoon=line.get("afternoon"),
                    total=line.get("total"),
                    notes=line.get("notes"),
                    confidence=line.get("confidence", {}),
                    bounding_boxes={
                        key: tuple(value) for key, value in line.get("bounding_boxes", {}).items()
                    },
                )
                for line in payload.get("lines", [])
            ],
            provider_name="http",
            model_name=self._model_name,
        )


@lru_cache
def get_vision_provider() -> VisionProvider:
    settings = get_settings()
    if settings.vision_provider == "fake":
        return FakeVisionProvider()
    if not (settings.vision_api_url and settings.vision_api_key):
        raise RuntimeError(
            "VISION_API_URL and VISION_API_KEY are required when VISION_PROVIDER=http"
        )
    return HttpVisionProvider(
        api_url=settings.vision_api_url,
        api_key=settings.vision_api_key.get_secret_value(),
        model_name=settings.vision_model_name,
    )

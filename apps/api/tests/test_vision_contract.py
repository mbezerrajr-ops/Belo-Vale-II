import pytest

from app.core.config import Settings
from app.vision.contracts import VisionExtraction
from app.vision.provider import FakeVisionProvider
import app.vision.provider as provider_module


def test_fake_provider_returns_structured_lines() -> None:
    result = FakeVisionProvider().extract(b"fixture")

    assert isinstance(result, VisionExtraction)
    assert result.lines[0].morning == "10"
    assert result.lines[0].confidence["morning"] == 0.98
    assert result.lot == "1"
    assert result.measured_on == "22/07/2026"


def test_http_provider_requires_a_server_side_key_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_module,
        "get_settings",
        lambda: Settings(environment="test", vision_provider="http"),
    )
    provider_module.get_vision_provider.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="VISION_API_URL"):
            provider_module.get_vision_provider()
    finally:
        provider_module.get_vision_provider.cache_clear()

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class VisionLine:
    #: Brinco lido da ficha. É a única chave de correspondência automática.
    animal_brinco: str | None
    #: Número e nome também são lidos e exibidos ao revisor como evidência,
    #: mas nunca são usados para casar automaticamente com um animal.
    animal_number: str | None
    animal_name: str | None
    morning: str | None
    afternoon: str | None
    total: str | None
    notes: str | None
    confidence: dict[str, float] = field(default_factory=dict)
    bounding_boxes: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class VisionExtraction:
    """Raw provider output. Never mutated after creation; the normalizer (Task 5)
    turns this into domain values without ever discarding this record."""

    header_text: str | None
    lot: str | None
    measured_on: str | None
    lines: list[VisionLine]
    provider_name: str
    model_name: str
    header_confidence: dict[str, float] = field(default_factory=dict)


class VisionProvider(Protocol):
    def extract(self, image_bytes: bytes) -> VisionExtraction: ...

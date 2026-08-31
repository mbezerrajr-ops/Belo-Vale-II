from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    corrected_values: dict[str, Any] | None = None
    reason: str | None = None
    expected_version: int

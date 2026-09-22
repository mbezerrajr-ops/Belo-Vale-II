from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ImportCreate(BaseModel):
    farm_id: UUID
    source: str | None = Field(default=None, max_length=255)


class ImportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    status: str
    source: str | None
    initiated_by: str | None
    created_at: datetime


class MediaAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_id: UUID | None
    sha256: str
    object_key: str | None
    media_type: str | None
    byte_size: int | None

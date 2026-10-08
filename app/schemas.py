from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class FileOut(BaseModel):
    id: str
    filename: str
    source_format: str
    status: str
    crs: str | None
    feature_count: int
    geometry_types: dict[str, int]
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("created_at", "completed_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite drops tzinfo; everything we store is UTC, so make that explicit in the API.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class FeatureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_index: int
    geometry_type: str | None
    geometry: dict[str, Any] | None
    crs: str
    properties: dict[str, Any]


class FeaturesPage(BaseModel):
    file_id: str
    total: int
    limit: int
    offset: int
    features: list[FeatureOut]


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feature_index: int
    geometry_type: str | None
    status: str
    area_sq_m: float | None
    perimeter_m: float | None
    length_m: float | None
    projected_crs: str | None
    note: str | None

    @classmethod
    def from_feature(cls, f) -> "MeasurementOut":
        return cls(
            feature_index=f.feature_index,
            geometry_type=f.geometry_type,
            status=f.measurement_status,
            area_sq_m=f.area_sq_m,
            perimeter_m=f.perimeter_m,
            length_m=f.length_m,
            projected_crs=f.projected_crs,
            note=f.measurement_note,
        )


class MeasurementSummary(BaseModel):
    total_area_sq_m: float
    total_length_m: float
    status_counts: dict[str, int]


class MeasurementsPage(BaseModel):
    file_id: str
    crs: str | None
    total: int
    limit: int
    offset: int
    summary: MeasurementSummary
    measurements: list[MeasurementOut]

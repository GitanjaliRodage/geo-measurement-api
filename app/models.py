from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileStatus:
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UploadedFile(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source_format: Mapped[str] = mapped_column(String(16))  # "shapefile" | "kml"
    status: Mapped[str] = mapped_column(String(16), default=FileStatus.PROCESSING)
    crs: Mapped[str | None] = mapped_column(String(128), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    features: Mapped[list["Feature"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )


class Feature(Base):
    __tablename__ = "features"
    __table_args__ = (Index("ix_features_file_idx", "file_id", "feature_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    feature_index: Mapped[int] = mapped_column(Integer)

    geometry_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    geometry: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # GeoJSON, in source CRS
    crs: Mapped[str] = mapped_column(String(128))  # source CRS of `geometry`
    properties: Mapped[dict] = mapped_column(JSON, default=dict)

    # Measurement results (all metric units).
    measurement_status: Mapped[str] = mapped_column(String(16))
    measurement_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    area_sq_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    perimeter_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    projected_crs: Mapped[str | None] = mapped_column(String(32), nullable=True)

    file: Mapped[UploadedFile] = relationship(back_populates="features")

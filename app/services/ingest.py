"""Orchestrates parse -> reproject -> measure -> persist for one uploaded file."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import shapely
from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import Feature, FileStatus, UploadedFile, utcnow
from app.services import measurements as m
from app.services.crs import Projector, crs_label
from app.services.parser import ParsedFeature, parse_upload

log = logging.getLogger(__name__)
INSERT_BATCH = 1000


def _feature_row(file_id: str, feat: ParsedFeature, crs: str, projector: Projector) -> dict:
    geom = feat.geometry
    try:
        wgs84 = projector.to_wgs84(geom) if geom is not None else None
        result = m.measure_geometry(wgs84, projector)
    except Exception as exc:  # one bad feature must never take down the whole file
        log.warning("Measurement failed for feature %s: %s", feat.index, exc)
        result = m.Measurement(m.ERROR, f"Measurement failed: {exc}")

    return {
        "file_id": file_id,
        "feature_index": feat.index,
        "geometry_type": geom.geom_type if geom is not None else None,
        "geometry": None if geom is None else json.loads(shapely.to_geojson(geom)),
        "crs": crs,
        "properties": feat.properties,
        "measurement_status": result.status,
        "measurement_note": result.note,
        "area_sq_m": result.area_sq_m,
        "perimeter_m": result.perimeter_m,
        "length_m": result.length_m,
        "projected_crs": result.projected_crs,
    }


def ingest(db: Session, record: UploadedFile, path: Path, workdir: Path) -> UploadedFile:
    """Parse and measure `path`, then store all features atomically.

    Raises ParseError if the file is unusable. Nothing is written for the features
    unless the whole file was processed, so a file is never half-stored.
    """
    parsed = parse_upload(path, record.source_format, workdir)
    projector = Projector(parsed.crs)
    label = crs_label(parsed.crs)

    rows = [_feature_row(record.id, f, label, projector) for f in parsed.features]
    for start in range(0, len(rows), INSERT_BATCH):
        db.execute(insert(Feature), rows[start : start + INSERT_BATCH])

    record.crs = label
    record.feature_count = len(rows)
    record.status = FileStatus.COMPLETED
    record.completed_at = utcnow()
    db.commit()
    return record

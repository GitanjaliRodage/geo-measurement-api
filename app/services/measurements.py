"""Area / length calculation. Never measures in degrees: always in a metric projected CRS."""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from app.services.crs import Projector

MEASURED = "MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"  # points: valid, nothing to measure
UNSUPPORTED = "UNSUPPORTED"  # geometry type we do not measure
EMPTY = "EMPTY"  # null / empty geometry
ERROR = "ERROR"  # reprojection or calculation failed for this feature

POLYGONAL = {"Polygon", "MultiPolygon"}
LINEAR = {"LineString", "MultiLineString"}
POINTLIKE = {"Point", "MultiPoint"}


@dataclass
class Measurement:
    status: str
    note: str | None = None
    area_sq_m: float | None = None
    perimeter_m: float | None = None
    length_m: float | None = None
    projected_crs: str | None = None


def _in_valid_range(geom_wgs84: BaseGeometry) -> bool:
    minx, miny, maxx, maxy = geom_wgs84.bounds
    values = (minx, miny, maxx, maxy)
    return all(math.isfinite(v) for v in values) and -180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90


def measure_geometry(geom_wgs84: BaseGeometry | None, projector: Projector) -> Measurement:
    """Measure one geometry that has already been converted to WGS84 (lon/lat)."""
    if geom_wgs84 is None or geom_wgs84.is_empty:
        return Measurement(EMPTY, "Feature has no geometry.")

    geom_type = geom_wgs84.geom_type
    if geom_type in POINTLIKE:
        return Measurement(NOT_APPLICABLE, "Points have no area or length.")
    if geom_type not in POLYGONAL | LINEAR:
        return Measurement(UNSUPPORTED, f"Measurement is not supported for geometry type '{geom_type}'.")

    if not _in_valid_range(geom_wgs84):
        return Measurement(ERROR, "Coordinates are outside the valid longitude/latitude range; check the file's CRS.")

    projected, epsg = projector.to_utm(geom_wgs84)
    note = None
    if geom_type in POLYGONAL:
        if not geom_wgs84.is_valid:
            note = f"Geometry is invalid ({explain_validity(geom_wgs84)}); area may be unreliable."
        return Measurement(
            MEASURED,
            note,
            area_sq_m=round(projected.area, 4),
            perimeter_m=round(projected.length, 4),
            projected_crs=f"EPSG:{epsg}",
        )
    return Measurement(MEASURED, note, length_m=round(projected.length, 4), projected_crs=f"EPSG:{epsg}")

"""CRS helpers: labelling, UTM zone selection and a small per-run transformer cache."""
from __future__ import annotations

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """Human-friendly identifier such as 'EPSG:4326' (falls back to the CRS name)."""
    try:
        authority = crs.to_authority(min_confidence=70)
    except Exception:  # pragma: no cover - defensive, pyproj raises on odd WKT
        authority = None
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.name or "UNKNOWN"


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG code of the UTM zone containing (lon, lat); UPS near the poles.

    WGS84 UTM codes: 326xx (north) / 327xx (south), where xx is the zone 1..60.
    Beyond 84N / 80S UTM is undefined, so Universal Polar Stereographic is used.
    """
    if lat >= 84:
        return 32661  # UPS North
    if lat <= -80:
        return 32761  # UPS South
    zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


class Projector:
    """Reprojects geometries for one uploaded file.

    Holds its own Transformer objects (instead of a global cache) because pyproj
    transformers should not be shared between the worker threads FastAPI uses.
    """

    def __init__(self, source_crs: CRS):
        self.source_crs = source_crs
        self._to_wgs84: Transformer | None = None
        if not source_crs.equals(WGS84, ignore_axis_order=True):
            self._to_wgs84 = Transformer.from_crs(source_crs, WGS84, always_xy=True)
        self._utm: dict[int, Transformer] = {}

    def to_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        if self._to_wgs84 is None:
            return geom
        return shapely_transform(self._to_wgs84.transform, geom)

    def to_utm(self, geom_wgs84: BaseGeometry) -> tuple[BaseGeometry, int]:
        """Project a WGS84 geometry into the UTM zone of its representative point."""
        point = geom_wgs84.representative_point()
        epsg = utm_epsg_for(point.x, point.y)
        if epsg not in self._utm:
            self._utm[epsg] = Transformer.from_crs(WGS84, CRS.from_epsg(epsg), always_xy=True)
        return shapely_transform(self._utm[epsg].transform, geom_wgs84), epsg

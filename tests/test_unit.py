import pytest
from pyproj import CRS, Geod
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from app.services import measurements as m
from app.services.crs import WGS84, Projector, crs_label, utm_epsg_for


@pytest.mark.parametrize(
    "lon,lat,expected",
    [
        (73.85, 18.52, 32643),  # Pune -> UTM 43N
        (-58.4, -34.6, 32721),  # Buenos Aires -> UTM 21S
        (-0.1, 51.5, 32630),  # London -> UTM 30N
        (179.99, 10, 32660),  # zone upper edge
        (-180, 10, 32601),  # zone lower edge
        (20, 88, 32661),  # polar north -> UPS
        (20, -85, 32761),  # polar south -> UPS
    ],
)
def test_utm_zone_selection(lon, lat, expected):
    assert utm_epsg_for(lon, lat) == expected


def test_crs_label():
    assert crs_label(CRS.from_epsg(4326)) == "EPSG:4326"
    assert crs_label(CRS.from_epsg(32643)) == "EPSG:32643"


def _measure(geom):
    return m.measure_geometry(geom, Projector(WGS84))


def test_polygon_area_matches_geodesic_area():
    poly = box(73.85, 18.52, 73.86, 18.53)  # ~1 km x 1 km in degrees
    result = _measure(poly)
    geodesic_area, geodesic_perimeter = Geod(ellps="WGS84").geometry_area_perimeter(poly)
    assert result.status == m.MEASURED
    assert result.projected_crs == "EPSG:32643"
    assert result.area_sq_m == pytest.approx(abs(geodesic_area), rel=1e-3)
    assert result.perimeter_m == pytest.approx(geodesic_perimeter, rel=1e-3)
    # The naive (wrong) answer would be 0.0001 "square degrees"; we must be in metres.
    assert result.area_sq_m > 1_000_000


def test_polygon_with_hole_subtracts_hole():
    outer = [(73.85, 18.52), (73.86, 18.52), (73.86, 18.53), (73.85, 18.53)]
    hole = [(73.853, 18.523), (73.857, 18.523), (73.857, 18.527), (73.853, 18.527)]
    full = _measure(Polygon(outer)).area_sq_m
    holed = _measure(Polygon(outer, [hole])).area_sq_m
    assert 0 < holed < full


def test_multipolygon_area_is_sum_of_parts():
    a, b = box(73.85, 18.52, 73.86, 18.53), box(73.90, 18.52, 73.91, 18.53)
    total = _measure(MultiPolygon([a, b])).area_sq_m
    assert total == pytest.approx(_measure(a).area_sq_m + _measure(b).area_sq_m, rel=1e-6)


def test_line_length_matches_geodesic_length():
    line = LineString([(73.85, 18.52), (73.90, 18.55)])
    result = _measure(line)
    assert result.length_m == pytest.approx(Geod(ellps="WGS84").geometry_length(line), rel=1e-3)
    assert result.area_sq_m is None


def test_southern_hemisphere_uses_south_zone():
    result = _measure(LineString([(-58.40, -34.60), (-58.30, -34.55)]))
    assert result.projected_crs == "EPSG:32721"
    assert result.length_m > 0


def test_point_is_not_applicable():
    assert _measure(Point(73.85, 18.52)).status == m.NOT_APPLICABLE


def test_empty_geometry():
    assert _measure(None).status == m.EMPTY
    assert _measure(Polygon()).status == m.EMPTY


def test_unsupported_geometry_type_is_handled():
    from shapely.geometry import GeometryCollection

    result = _measure(GeometryCollection([Point(73.85, 18.52), LineString([(73.85, 18.52), (73.86, 18.53)])]))
    assert result.status == m.UNSUPPORTED
    assert "GeometryCollection" in result.note


def test_invalid_polygon_is_measured_with_warning():
    bowtie = Polygon([(73.85, 18.52), (73.86, 18.53), (73.86, 18.52), (73.85, 18.53)])
    result = _measure(bowtie)
    assert result.status == m.MEASURED
    assert "invalid" in result.note.lower()


def test_out_of_range_coordinates_flagged():
    result = _measure(LineString([(500000, 2050000), (500100, 2050100)]))
    assert result.status == m.ERROR

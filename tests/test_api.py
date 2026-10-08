import io
import zipfile

import pytest
from pyproj import Geod
from shapely.geometry import LineString, Point, box

from app.config import settings
from tests.conftest import upload
from tests.helpers import (
    KML_LINE, KML_MULTI, KML_POINT, KML_POLYGON, SQUARE_UTM, UTM_43N,
    kml_bytes, shapefile_zip, zip_directory,
)

GEOD = Geod(ellps="WGS84")


# ------------------------------------------------------------------ shapefile


def test_shapefile_in_projected_crs(client, tmp_path):
    zipped = shapefile_zip(tmp_path, [SQUARE_UTM], UTM_43N, props={"owner": ["Asha"]})
    resp = upload(client, "survey.zip", zipped)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "COMPLETED"
    assert body["crs"] == "EPSG:32643"
    assert body["feature_count"] == 1
    assert body["geometry_types"] == {"Polygon": 1}

    meas = client.get(f"/api/files/{body['id']}/measurements/").json()
    item = meas["measurements"][0]
    assert item["status"] == "MEASURED"
    assert item["area_sq_m"] == pytest.approx(1_000_000, abs=0.01)
    assert item["perimeter_m"] == pytest.approx(4_000, abs=0.01)
    assert item["projected_crs"] == "EPSG:32643"


def test_shapefile_in_geographic_crs_is_not_measured_in_degrees(client, tmp_path):
    poly = box(73.85, 18.52, 73.86, 18.53)
    resp = upload(client, "geo.zip", shapefile_zip(tmp_path, [poly], "EPSG:4326"))
    assert resp.json()["crs"] == "EPSG:4326"

    item = client.get(f"/api/files/{resp.json()['id']}/measurements/").json()["measurements"][0]
    geodesic_area = abs(GEOD.geometry_area_perimeter(poly)[0])
    assert item["area_sq_m"] == pytest.approx(geodesic_area, rel=1e-3)
    assert item["area_sq_m"] > 1_000_000  # square metres, not 0.0001 square degrees


def test_projected_and_geographic_versions_of_same_shape_agree(client, tmp_path):
    import geopandas as gpd

    in_wgs84 = gpd.GeoSeries([SQUARE_UTM], crs=UTM_43N).to_crs(4326).iloc[0]
    a = upload(client, "a.zip", shapefile_zip(tmp_path, [SQUARE_UTM], UTM_43N, name="a")).json()["id"]
    b = upload(client, "b.zip", shapefile_zip(tmp_path, [in_wgs84], "EPSG:4326", name="b")).json()["id"]
    area_a = client.get(f"/api/files/{a}/measurements/").json()["measurements"][0]["area_sq_m"]
    area_b = client.get(f"/api/files/{b}/measurements/").json()["measurements"][0]["area_sq_m"]
    assert area_a == pytest.approx(area_b, rel=1e-6)


def test_shapefile_in_zip_subfolder_and_uppercase_names(client, tmp_path):
    folder = tmp_path / "raw"
    folder.mkdir()
    import geopandas as gpd

    gpd.GeoDataFrame({"geometry": [SQUARE_UTM]}, crs=UTM_43N).to_file(folder / "data.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in folder.iterdir():
            zf.write(p, f"Export/Nested/{p.name.upper()}")
    zf_bytes = buf.getvalue()
    resp = upload(client, "nested.zip", zf_bytes)
    assert resp.status_code == 201, resp.text
    assert resp.json()["feature_count"] == 1


def test_line_shapefile_length(client, tmp_path):
    line = LineString([(380_000, 2_050_000), (383_000, 2_054_000)])  # 3-4-5 triangle -> 5000 m
    resp = upload(client, "roads.zip", shapefile_zip(tmp_path, [line], UTM_43N))
    item = client.get(f"/api/files/{resp.json()['id']}/measurements/").json()["measurements"][0]
    assert item["length_m"] == pytest.approx(5000, abs=0.01)
    assert item["area_sq_m"] is None


def test_attributes_are_returned(client, tmp_path):
    zipped = shapefile_zip(tmp_path, [SQUARE_UTM], UTM_43N, props={"owner": ["Asha"], "acres": [2.5]})
    file_id = upload(client, "s.zip", zipped).json()["id"]
    feature = client.get(f"/api/files/{file_id}/features/").json()["features"][0]
    assert feature["properties"] == {"owner": "Asha", "acres": 2.5}
    assert feature["geometry_type"] == "Polygon"
    assert feature["crs"] == "EPSG:32643"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["feature_index"] == 0


# ------------------------------------------------------------------------ kml


def test_kml_polygon_line_point(client):
    resp = upload(client, "survey.kml", kml_bytes(KML_POLYGON, KML_LINE, KML_POINT))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["crs"] == "EPSG:4326"
    assert body["feature_count"] == 3
    assert body["geometry_types"] == {"Polygon": 1, "LineString": 1, "Point": 1}

    meas = client.get(f"/api/files/{body['id']}/measurements/").json()
    by_type = {mm["geometry_type"]: mm for mm in meas["measurements"]}

    poly = box(73.85, 18.52, 73.86, 18.53)
    assert by_type["Polygon"]["area_sq_m"] == pytest.approx(abs(GEOD.geometry_area_perimeter(poly)[0]), rel=1e-3)
    line = LineString([(73.85, 18.52), (73.86, 18.52), (73.87, 18.53)])
    assert by_type["LineString"]["length_m"] == pytest.approx(GEOD.geometry_length(line), rel=1e-3)
    assert by_type["Point"]["status"] == "NOT_APPLICABLE"
    assert by_type["Point"]["area_sq_m"] is None and by_type["Point"]["length_m"] is None
    assert meas["summary"]["status_counts"] == {"MEASURED": 2, "NOT_APPLICABLE": 1}


def test_kml_properties_and_3d_coordinates_are_handled(client):
    file_id = upload(client, "k.kml", kml_bytes(KML_POLYGON)).json()["id"]
    feature = client.get(f"/api/files/{file_id}/features/").json()["features"][0]
    assert feature["properties"]["Name"] == "Plot A"
    # Z values (",0") were dropped: every stored coordinate is [lon, lat].
    assert all(len(c) == 2 for c in feature["geometry"]["coordinates"][0])


def test_kml_unsupported_geometry_is_handled_gracefully(client):
    resp = upload(client, "mixed.kml", kml_bytes(KML_POLYGON, KML_MULTI))
    assert resp.status_code == 201
    meas = client.get(f"/api/files/{resp.json()['id']}/measurements/").json()
    statuses = sorted(mm["status"] for mm in meas["measurements"])
    assert statuses == ["MEASURED", "UNSUPPORTED"]
    unsupported = next(mm for mm in meas["measurements"] if mm["status"] == "UNSUPPORTED")
    assert "not supported" in unsupported["note"]
    assert unsupported["area_sq_m"] is None


# ------------------------------------------------------------------ endpoints


def test_file_info_shape(client):
    file_id = upload(client, "survey.kml", kml_bytes(KML_POLYGON)).json()["id"]
    body = client.get(f"/api/files/{file_id}/").json()
    assert body["id"] == file_id
    assert body["filename"] == "survey.kml"
    assert body["feature_count"] == 1
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    assert body["created_at"].endswith(("Z", "+00:00"))  # timestamps are explicit UTC


def test_pagination_and_summary_cover_whole_file(client):
    placemarks = [KML_POLYGON, KML_LINE, KML_POINT] * 4  # 12 features
    file_id = upload(client, "many.kml", kml_bytes(*placemarks)).json()["id"]
    page1 = client.get(f"/api/files/{file_id}/measurements/?limit=5&offset=0").json()
    page3 = client.get(f"/api/files/{file_id}/measurements/?limit=5&offset=10").json()
    assert page1["total"] == 12
    assert [m["feature_index"] for m in page1["measurements"]] == [0, 1, 2, 3, 4]
    assert [m["feature_index"] for m in page3["measurements"]] == [10, 11]
    # Summary is computed over all features, not just the requested page.
    assert page1["summary"]["status_counts"] == {"MEASURED": 8, "NOT_APPLICABLE": 4}
    assert page1["summary"]["total_area_sq_m"] == page3["summary"]["total_area_sq_m"] > 0


@pytest.mark.parametrize("path", ["", "measurements/", "features/"])
def test_unknown_file_id_returns_404(client, path):
    assert client.get(f"/api/files/doesnotexist/{path}").status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=5000", "offset=-1"])
def test_invalid_pagination_params_rejected(client, query):
    file_id = upload(client, "k.kml", kml_bytes(KML_POLYGON)).json()["id"]
    assert client.get(f"/api/files/{file_id}/measurements/?{query}").status_code == 422


# --------------------------------------------------------------------- errors


def test_unsupported_extension(client):
    resp = upload(client, "notes.txt", b"hello")
    assert resp.status_code == 415


def test_corrupt_zip_is_recorded_as_failed(client):
    resp = upload(client, "bad.zip", b"this is not a zip")
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["status"] == "FAILED"
    info = client.get(f"/api/files/{detail['id']}/").json()
    assert info["status"] == "FAILED"
    assert "zip" in info["error_message"].lower()
    # Results of a failed file are not served.
    assert client.get(f"/api/files/{detail['id']}/measurements/").status_code == 409


def test_zip_without_shapefile(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "no shapefile here")
    resp = upload(client, "empty.zip", buf.getvalue())
    assert resp.status_code == 422
    assert "No .shp" in resp.json()["detail"]["message"]


def test_shapefile_without_prj_is_rejected(client, tmp_path):
    folder = tmp_path / "noprj"
    folder.mkdir()
    import geopandas as gpd

    gpd.GeoDataFrame({"geometry": [SQUARE_UTM]}, crs=UTM_43N).to_file(folder / "p.shp")
    (folder / "p.prj").unlink()
    resp = upload(client, "noprj.zip", zip_directory(folder))
    assert resp.status_code == 422
    assert "coordinate reference system" in resp.json()["detail"]["message"]


def test_zip_with_multiple_shapefiles_is_rejected(client, tmp_path):
    import geopandas as gpd

    folder = tmp_path / "two"
    folder.mkdir()
    for name in ("a", "b"):
        gpd.GeoDataFrame({"geometry": [SQUARE_UTM]}, crs=UTM_43N).to_file(folder / f"{name}.shp")
    resp = upload(client, "two.zip", zip_directory(folder))
    assert resp.status_code == 422
    assert "more than one" in resp.json()["detail"]["message"]


def test_invalid_kml(client):
    resp = upload(client, "broken.kml", b"<kml><not closed")
    assert resp.status_code == 422
    assert resp.json()["detail"]["status"] == "FAILED"


def test_kml_with_no_features(client):
    resp = upload(client, "empty.kml", kml_bytes())
    assert resp.status_code == 422


def test_upload_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    resp = upload(client, "k.kml", kml_bytes(KML_POLYGON))
    assert resp.status_code == 413


def test_zip_slip_member_paths_cannot_escape(client, tmp_path):
    import geopandas as gpd

    folder = tmp_path / "slip"
    folder.mkdir()
    gpd.GeoDataFrame({"geometry": [SQUARE_UTM]}, crs=UTM_43N).to_file(folder / "p.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for p in folder.iterdir():
            zf.write(p, f"../../{p.name}")  # hostile member paths
    resp = upload(client, "slip.zip", buf.getvalue())
    assert resp.status_code == 201  # processed safely using flattened names
    assert not (tmp_path.parent / "p.shp").exists()


def test_zip_expansion_limit(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "max_zip_uncompressed_mb", 0)
    resp = upload(client, "s.zip", shapefile_zip(tmp_path, [SQUARE_UTM], UTM_43N))
    assert resp.status_code == 422
    assert "allowed size" in resp.json()["detail"]["message"]


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}

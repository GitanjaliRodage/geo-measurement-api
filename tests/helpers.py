import io
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

# A 1000 m x 1000 m square in UTM zone 43N (around Pune, India): area is exactly 1,000,000 m2.
UTM_43N = "EPSG:32643"
SQUARE_UTM = box(380_000, 2_050_000, 381_000, 2_051_000)

KML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{body}</Document></kml>"""

KML_POLYGON = """<Placemark><name>Plot A</name><description>Test plot</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
73.85,18.52,0 73.86,18.52,0 73.86,18.53,0 73.85,18.53,0 73.85,18.52,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"""

KML_LINE = """<Placemark><name>Road</name>
<LineString><coordinates>73.85,18.52 73.86,18.52 73.87,18.53</coordinates></LineString></Placemark>"""

KML_POINT = """<Placemark><name>Well</name><Point><coordinates>73.855,18.525</coordinates></Point></Placemark>"""

KML_MULTI = """<Placemark><name>Mixed</name><MultiGeometry>
<Point><coordinates>73.85,18.52</coordinates></Point>
<LineString><coordinates>73.85,18.52 73.86,18.53</coordinates></LineString>
</MultiGeometry></Placemark>"""


def kml_bytes(*placemarks: str) -> bytes:
    return KML_TEMPLATE.format(body="".join(placemarks)).encode()


def zip_directory(directory: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(directory.iterdir()):
            zf.write(path, path.name)
    return buf.getvalue()


def shapefile_zip(tmp_path: Path, geometries, crs: str, name: str = "parcels", props: dict | None = None) -> bytes:
    """Write geometries to a real Shapefile with geopandas and return it zipped."""
    folder = tmp_path / f"shp_{name}"
    folder.mkdir()
    data = {"geometry": list(geometries)}
    data.update(props or {"plot_id": list(range(len(data["geometry"])))})
    gpd.GeoDataFrame(data, crs=crs).to_file(folder / f"{name}.shp")
    return zip_directory(folder)

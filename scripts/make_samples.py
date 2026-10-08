"""Generate sample input files in ./samples (run from the project root)."""
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

OUT = Path(__file__).resolve().parent.parent / "samples"
OUT.mkdir(exist_ok=True)

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>Plot A</name><description>Farm plot</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>
73.85,18.52,0 73.86,18.52,0 73.86,18.53,0 73.85,18.53,0 73.85,18.52,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>Access road</name>
<LineString><coordinates>73.85,18.52 73.86,18.52 73.87,18.53</coordinates></LineString></Placemark>
<Placemark><name>Water well</name><Point><coordinates>73.855,18.525</coordinates></Point></Placemark>
<Placemark><name>Mixed marker</name><MultiGeometry>
<Point><coordinates>73.85,18.52</coordinates></Point>
<LineString><coordinates>73.85,18.52 73.86,18.53</coordinates></LineString>
</MultiGeometry></Placemark>
</Document></kml>
"""
(OUT / "sample_survey.kml").write_text(KML)

# Shapefile in a *projected* CRS (UTM 43N) to show CRS handling: one 1 km x 1 km parcel.
# (A Shapefile holds a single geometry type, so this sample contains polygons only.)
with tempfile.TemporaryDirectory() as tmp:
    gdf = gpd.GeoDataFrame(
        {"name": ["Parcel 1"], "owner": ["Asha"], "geometry": [box(380_000, 2_050_000, 381_000, 2_051_000)]},
        crs="EPSG:32643",
    )
    gdf.to_file(Path(tmp) / "parcels.shp")
    with zipfile.ZipFile(OUT / "sample_parcels_utm43n.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(Path(tmp).iterdir()):
            zf.write(p, p.name)

print("Wrote:", *sorted(p.name for p in OUT.iterdir()))

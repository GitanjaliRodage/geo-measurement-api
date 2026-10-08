# Geospatial File Measurement API

This is a backend service I built with FastAPI. You upload a Shapefile (as a `.zip`) or a KML file, and it
gives back the area of every polygon and the length of every line in it, in metres and square metres.

The main thing I wanted to get right is that the numbers are actually correct. Latitude/longitude are angles,
not distances, so I never calculate area or length on them directly. Everything is converted to a proper
metric coordinate system first (details in the CRS section below).

**Stack:** Python, FastAPI, SQLAlchemy (SQLite), GeoPandas/pyogrio, Shapely, pyproj

Once it is running, the interactive API docs are at `/docs`.

---

## Setup

```bash
git clone https://github.com/GitanjaliRodage/geo-measurement-api.git
cd geo-measurement-api

python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs.

You don't need to install GDAL or PROJ separately, because the Python packages already include them.
The SQLite database file is created automatically the first time the app starts.

**Running the tests**

```bash
pytest
```

**Try it with the sample files** in the `samples/` folder:

- `sample_survey.kml` has a polygon, a line, a point and one `MultiGeometry` (which the API reports as unsupported instead of crashing).
- `sample_parcels_utm43n.zip` is a Shapefile that is already in a projected CRS (EPSG:32643).

You can regenerate them with `python scripts/make_samples.py`.

**Settings** (all optional, set as environment variables)

| Variable | Default | What it does |
|---|---|---|
| `GEO_DATABASE_URL` | `sqlite:///./geo_api.db` | Database to use (any SQLAlchemy URL works, e.g. Postgres) |
| `GEO_MAX_UPLOAD_MB` | `50` | Largest upload allowed |
| `GEO_MAX_ZIP_UNCOMPRESSED_MB` | `500` | Largest size a zip may expand to |
| `GEO_MAX_ZIP_MEMBERS` | `200` | Most files allowed inside a zip |

---

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/files/` | Upload and process a `.kml` or a `.zip` Shapefile |
| `GET` | `/api/files/{id}/` | File info and status |
| `GET` | `/api/files/{id}/measurements/` | Measurements for every feature, plus totals |
| `GET` | `/api/files/{id}/features/` | Geometry, CRS and attributes of every feature |
| `GET` | `/health` | Simple check that the server is up |

### Upload a file

```bash
curl -X POST http://localhost:8000/api/files/ -F "file=@samples/sample_survey.kml"
```

Response (`201 Created`):

```json
{
  "id": "f1203de4336945aebbf7935a6655fa68",
  "filename": "sample_survey.kml",
  "source_format": "kml",
  "status": "COMPLETED",
  "crs": "EPSG:4326",
  "feature_count": 4,
  "geometry_types": { "GeometryCollection": 1, "LineString": 1, "Point": 1, "Polygon": 1 },
  "error_message": null,
  "created_at": "2026-10-07T04:58:53.994066Z",
  "completed_at": "2026-10-07T04:58:54.016519Z"
}
```

I process the file during the upload request, so by the time you get this response the status is already `COMPLETED`
(or `FAILED` if the file was unusable).

### Get file info

`GET /api/files/{id}/` returns the same object as above.

### Get measurements

`GET /api/files/{id}/measurements/?limit=100&offset=0`

```json
{
  "file_id": "f1203de4336945aebbf7935a6655fa68",
  "crs": "EPSG:4326",
  "total": 4,
  "limit": 100,
  "offset": 0,
  "summary": {
    "total_area_sq_m": 1168194.0429,
    "total_length_m": 2585.0406,
    "status_counts": { "MEASURED": 2, "NOT_APPLICABLE": 1, "UNSUPPORTED": 1 }
  },
  "measurements": [
    { "feature_index": 0, "geometry_type": "Polygon", "status": "MEASURED",
      "area_sq_m": 1168194.0429, "perimeter_m": 4324.5232, "length_m": null,
      "projected_crs": "EPSG:32643", "note": null },
    { "feature_index": 1, "geometry_type": "LineString", "status": "MEASURED",
      "area_sq_m": null, "perimeter_m": null, "length_m": 2585.0406,
      "projected_crs": "EPSG:32643", "note": null },
    { "feature_index": 2, "geometry_type": "Point", "status": "NOT_APPLICABLE",
      "area_sq_m": null, "perimeter_m": null, "length_m": null,
      "projected_crs": null, "note": "Points have no area or length." },
    { "feature_index": 3, "geometry_type": "GeometryCollection", "status": "UNSUPPORTED",
      "area_sq_m": null, "perimeter_m": null, "length_m": null,
      "projected_crs": null, "note": "Measurement is not supported for geometry type 'GeometryCollection'." }
  ]
}
```

All values are in metres or square metres. The `summary` covers the whole file, not only the page you asked for.

Each feature gets one of these statuses:

| Status | Meaning |
|---|---|
| `MEASURED` | Polygon or MultiPolygon (area and perimeter), or LineString or MultiLineString (length) |
| `NOT_APPLICABLE` | Point or MultiPoint. It is valid, there is just nothing to measure |
| `UNSUPPORTED` | A geometry type I don't measure, such as `GeometryCollection` |
| `EMPTY` | The feature has no geometry |
| `ERROR` | Something went wrong with this one feature (the reason is in `note`) |

### Get features

`GET /api/files/{id}/features/?limit=100&offset=0` returns each feature's index, geometry type, geometry (GeoJSON),
CRS and its attributes:

```json
{
  "file_id": "…", "total": 4, "limit": 100, "offset": 0,
  "features": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "geometry": { "type": "Polygon", "coordinates": [[[73.85, 18.52], [73.86, 18.52], "…"]] },
      "crs": "EPSG:4326",
      "properties": { "Name": "Plot A", "description": "Farm plot" }
    }
  ]
}
```

The geometry is returned in the file's original CRS (the `crs` field tells you which). Z values are dropped.

### Errors

| Code | When it happens |
|---|---|
| `404` | The file id doesn't exist |
| `409` | You asked for results of a file that isn't `COMPLETED` |
| `413` | The upload is bigger than the limit |
| `415` | The file isn't a `.kml` or `.zip` |
| `422` | The file can't be read: corrupt zip, no `.shp` inside, more than one Shapefile, no CRS, broken or empty KML. The file is saved with status `FAILED` and the response includes its `id` and a clear message |

---

## Architecture

### How the code is organised

```
app/
  main.py              creates the FastAPI app
  config.py            settings
  database.py          database connection
  models.py            two tables: UploadedFile and Feature
  schemas.py           response models
  api/files.py         the endpoints
  services/
    parser.py          reads KML and zipped Shapefiles
    crs.py             CRS names, UTM zone choice, reprojection
    measurements.py    works out area and length
    ingest.py          ties parsing, measuring and saving together
tests/                 unit tests and API tests
scripts/make_samples.py
```

I kept the web layer (`api/`) separate from the geospatial logic (`services/`). The endpoints don't know anything
about GDAL or projections, and `measurements.py` doesn't do any I/O, which made it easy to test with shapes whose
correct answer I already knew.

### What happens when you upload a file

1. The endpoint checks the extension and saves the upload to a temporary folder, stopping if it is too large.
2. A row is created in the database with status `PROCESSING`.
3. **Shapefile:** the zip is extracted safely. It must contain exactly one `.shp`, and the `.prj` must give a CRS.
   **KML:** every folder in the KML is read, and the CRS is WGS84 (that is what KML always uses).
4. Each feature is turned into an index, a 2D geometry and its attributes.
5. Each feature is reprojected and measured. If one feature fails, it is stored with status `ERROR`
   and the rest of the file carries on.
6. All the features are saved and the file is marked `COMPLETED` in a single transaction, so a file is never
   left half-saved.
7. If the file can't be used at all, it is marked `FAILED` with the reason and the API returns `422`.
8. The temporary folder, including the uploaded file, is deleted.

### How a measurement is calculated

```
geometry in the file's own CRS
   ↓  drop Z values
convert to WGS84 (lon/lat)             (skipped if it already is WGS84)
   ↓  take a point inside the shape, find its UTM zone
convert to that UTM zone (metres)
   ↓
Polygon / MultiPolygon        → area and perimeter (holes are subtracted)
LineString / MultiLineString  → length
Point / MultiPoint            → NOT_APPLICABLE
anything else, or empty       → UNSUPPORTED / EMPTY
```

### How I handle CRS

- The source CRS comes from the file: the `.prj` for a Shapefile, WGS84 for KML. It is reported as `EPSG:xxxx`
  whenever it can be identified.
- Everything is first converted to WGS84, then to the UTM zone of the feature (`EPSG:326xx` in the northern
  hemisphere, `EPSG:327xx` in the southern). Near the poles (north of 84°N or south of 80°S) UTM isn't defined,
  so I use the polar stereographic systems (`EPSG:32661` / `EPSG:32761`) instead.
- The zone is picked per feature, so a file that spreads over several zones is still handled sensibly.
- Every measurement says which zone was used (`projected_crs`), so you can see how it was computed.
- A Shapefile with no CRS is rejected. I preferred that over guessing and returning wrong numbers.
- If the converted coordinates fall outside the valid lat/lon range, that usually means the CRS in the file is wrong,
  so that feature is marked `ERROR`.

**How I checked it is correct:** I compare my results with `pyproj.Geod`, which computes true distances and areas on
the ellipsoid, and they match within 0.1%. I also test a 1000 m × 1000 m square in UTM, which must come out as exactly
1,000,000 m², and I upload the same shape once in EPSG:32643 and once in EPSG:4326 to make sure both give the same area.
To be sure the tests really protect this logic, I temporarily removed the projection step and 7 tests failed.

---

## Design decisions

**FastAPI instead of Django.** The project is a small API with no admin pages or templates, so FastAPI's type
checking, automatic docs and simple file uploads were a better fit than Django REST Framework.

**Processing during the upload request, not in the background.** The files in this assignment are processed in tens of
milliseconds, and "upload, then get results" is the simplest contract. Endpoints are normal `def` functions, so FastAPI
runs them in a thread pool and doesn't block other requests. For very large files I would move this to a job queue
(for example Celery with Redis). The `PROCESSING` status already exists for that.

**UTM zone for each feature.** It is accurate (distortion is well under 0.1% inside a zone), it works in metres,
and the zone can be worked out from a single coordinate with no lookup. I considered:
- one CRS for the whole file, which is simpler but wrong for files that cross zones;
- measuring directly on the ellipsoid with `pyproj.Geod`, which is the most accurate, but the assignment asks for projection, so I use it as an independent check in the tests;
- equal-area projections like EPSG:6933, which are great for area but not for length.

**Always going through WGS84 first.** One code path handles any input CRS, and I avoid measuring in a CRS that is
itself distorted (Web Mercator, for example, inflates areas a lot away from the equator).

**GeoPandas/pyogrio for reading.** One reader handles both Shapefile and KML, including `.prj` parsing and
KML folders. Using `fastkml` and `pyshp` would have meant two separate code paths.

**Saving results in a database.** Measurements are calculated once, and the GET endpoints are cheap, paginated and
survive restarts. SQLite works with no setup, and changing `GEO_DATABASE_URL` is enough to move to Postgres.

**Unsupported or broken features get a status instead of an error.** One `GeometryCollection` shouldn't make the
other 9,999 features in a file unusable.

**Geometry is returned in the file's original CRS.** I didn't want to silently change the user's data. The `crs` field
says how to read the coordinates.

**One Shapefile per zip.** Merging several would raise questions about mixed CRSs and feature numbering.

### Security

- Files inside a zip are never extracted using their path from the archive, which prevents zip-slip. Only known Shapefile
  extensions are written, to fixed names in a temporary folder.
- The size a zip expands to is checked while extracting, not by trusting the size written in the header, and the number
  of files is limited too (protection against zip bombs).
- Uploads are streamed to disk with a size limit, so a big file is never loaded fully into memory.
- Temporary files are always cleaned up.

### Limitations I know about

- `GeometryCollection` and KML `MultiGeometry` features are reported as `UNSUPPORTED` instead of being measured part by part.
- Features that cross the antimeridian (±180°) or span more than one UTM zone are measured in the zone of one
  representative point, which is slightly less accurate than a full geodesic calculation.
- Z values are discarded, so all measurements are 2D.
- `.kmz` files and zips with several Shapefiles are not accepted.
- There is no authentication or rate limiting.

---

## What I learned

- **Degrees are not distances.** One degree of longitude is about 111 km at the equator and shrinks towards the
  poles, so "area in square degrees" is meaningless. This was the biggest lesson, and the whole design comes from it.
- **Geographic vs projected CRS.** EPSG:4326 stores positions as angles. A projected CRS like UTM stores them in metres,
  which is what you need to measure. Learning how a UTM zone follows from a longitude was really useful.
- **Not all projections are good for measuring.** Web Mercator is great for web maps but distorts area badly.
- **How to test geospatial code.** Because there is no "obvious" answer, I used independent checks: true geodesic
  calculations, shapes with a known exact answer, and comparing the same shape in two different CRSs. I also broke the
  code on purpose to make sure the tests would catch it.
- **Dealing with untrusted uploads.** Zip-slip, zip bombs and size limits were new to me, and now I check for them whenever
  I accept a file.
- **Designing for partial failure.** Giving each feature its own status is much more useful to a client than failing
  the whole file because of one bad feature.

## What I would do next

- Move processing to a background job queue (Celery or RQ with Redis) with progress reporting for very large files.
- Measure `GeometryCollection` and `MultiGeometry` features part by part.
- Add an option for geodesic measurement and for choosing units (hectares, acres, kilometres, miles).
- Support `.kmz`, GeoJSON, GeoPackage and zips with several layers.
- Use PostGIS so features can be queried spatially (for example by bounding box).
- Add authentication, file cleanup and a `DELETE` endpoint.
- Add database migrations with Alembic, structured logging and a GitHub Actions workflow that runs the tests.

# Geospatial File Measurement API

A FastAPI backend that accepts a **Shapefile (`.zip`)** or **KML** file, extracts every feature
(ID, geometry type, geometry, CRS, attributes) and returns **area** (polygons) and **length**
(lines), calculated in a projected, metric coordinate system, never in degrees.

- Python 3.10+ · FastAPI · SQLAlchemy (SQLite by default) · GeoPandas / pyogrio (GDAL) · Shapely · pyproj
- Interactive docs at `/docs` (Swagger UI) once the server is running
- 46 automated tests, including known-answer checks against independent geodesic calculations

---

## Setup

```bash
git clone <your-repo-url> && cd geo-measurement-api

python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn app.main:app --reload        # http://127.0.0.1:8000  (docs at /docs)
```

No system GDAL/PROJ install is needed: the `pyogrio`, `shapely` and `pyproj` wheels bundle them.
The SQLite database (`geo_api.db`) is created automatically on first start.

**Run the tests**

```bash
pytest
```

**Docker (optional)**

```bash
docker build -t geo-api .
docker run -p 8000:8000 geo-api
```

**Sample files** are in `samples/` (regenerate with `python scripts/make_samples.py`):

| File | What it shows |
|---|---|
| `sample_survey.kml` | Polygon, line, point, and a `MultiGeometry` (unsupported type handled gracefully) |
| `sample_parcels_utm43n.zip` | Shapefile already in a projected CRS (EPSG:32643) |

**Configuration** (environment variables, all optional)

| Variable | Default | Meaning |
|---|---|---|
| `GEO_DATABASE_URL` | `sqlite:///./geo_api.db` | Any SQLAlchemy URL (e.g. Postgres) |
| `GEO_MAX_UPLOAD_MB` | `50` | Maximum upload size |
| `GEO_MAX_ZIP_UNCOMPRESSED_MB` | `500` | Maximum size a zip may expand to |
| `GEO_MAX_ZIP_MEMBERS` | `200` | Maximum number of files inside a zip |

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/files/` | Upload and process a `.kml` or `.zip` (Shapefile) |
| `GET` | `/api/files/{id}/` | File information and processing status |
| `GET` | `/api/files/{id}/measurements/` | Per-feature measurements + file-level summary (paginated) |
| `GET` | `/api/files/{id}/features/` | Per-feature geometry, CRS and attributes (paginated) |
| `GET` | `/health` | Liveness check |

### Upload: `POST /api/files/`

```bash
curl -X POST http://localhost:8000/api/files/ -F "file=@samples/sample_survey.kml"
```

`201 Created`

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

### File information: `GET /api/files/{id}/`

Returns the same object as above (the shape from the assignment: `id`, `filename`, `feature_count`,
`crs`, `status`, plus a few extra fields). `status` is `PROCESSING`, `COMPLETED` or `FAILED`.

### Measurements: `GET /api/files/{id}/measurements/?limit=100&offset=0`

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

All values are metric (square metres / metres). `summary` covers the **whole file**, not just the current page.

| `status` | Meaning |
|---|---|
| `MEASURED` | Polygon/MultiPolygon (area, perimeter) or LineString/MultiLineString (length) |
| `NOT_APPLICABLE` | Point/MultiPoint, valid, but nothing to measure |
| `UNSUPPORTED` | Geometry type we don't measure (e.g. `GeometryCollection`) |
| `EMPTY` | Feature has a null/empty geometry |
| `ERROR` | Reprojection/calculation failed for this one feature (see `note`) |

### Features: `GET /api/files/{id}/features/?limit=100&offset=0`

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

`geometry` is GeoJSON in the **file's original CRS** (stated in `crs`); Z values are dropped.

### Errors

| Code | When |
|---|---|
| `404` | Unknown file id |
| `409` | Results requested for a file whose status is not `COMPLETED` |
| `413` | Upload larger than `GEO_MAX_UPLOAD_MB` |
| `415` | Not a `.kml` / `.zip` |
| `422` | File is unreadable (corrupt zip, no `.shp`, more than one Shapefile, no CRS, invalid/empty KML, zip too large when expanded). The file is recorded with status `FAILED` and the response body contains its `id` and a clear `message` |

---

## Architecture

### Application structure

```
app/
  main.py              FastAPI app, router registration, DB init on startup
  config.py            Settings (env-driven)
  database.py          Engine / session / get_db dependency
  models.py            UploadedFile, Feature (SQLAlchemy)
  schemas.py           Pydantic response models
  api/files.py         HTTP layer: validation of the upload, endpoints, error mapping
  services/
    parser.py          Zip extraction + reading KML/Shapefile into plain Python objects
    crs.py             CRS labelling, UTM zone selection, Projector (reprojection)
    measurements.py    Pure functions: geometry in WGS84 -> Measurement
    ingest.py          Orchestrates parse -> reproject -> measure -> persist
tests/                 Unit tests (CRS/measurement) + API tests with real generated files
scripts/make_samples.py
```

The HTTP layer knows nothing about GDAL or projections; the services know nothing about HTTP.
`measurements.py` is pure (no I/O), which is why it is easy to unit test against known answers.

### File-processing flow

1. `POST /api/files/` checks the extension, streams the body to a temp directory while enforcing the size limit.
2. A `files` row is created with status `PROCESSING`.
3. **Shapefile:** the zip is safely extracted (see *Security*), exactly one `.shp` is required, and the `.prj` must yield a CRS.
   **KML:** every Folder (GDAL layer) is read and concatenated; CRS is WGS84 by definition of KML.
4. Each feature becomes `(index, 2D geometry, JSON-safe attributes)`.
5. Each feature is reprojected and measured (below). A failure on one feature is caught and stored as `ERROR`; it never fails the file.
6. All feature rows are inserted in batches and the file is marked `COMPLETED` **in one transaction**, so a file is never stored half-processed.
7. If the file is unusable, the file row is marked `FAILED` with the reason and the API returns `422`.
8. The temp directory (including the uploaded file) is deleted; only the extracted data is kept.

### Measurement-calculation flow

```
geometry (source CRS)
   │  force 2D
   ▼
reproject → WGS84 (lon/lat)         ← skipped if already WGS84
   │  representative_point() → pick UTM zone
   ▼
reproject → UTM zone (metres)
   │
   ├─ Polygon / MultiPolygon        → area, perimeter  (holes are subtracted; parts summed)
   ├─ LineString / MultiLineString  → length
   ├─ Point / MultiPoint            → NOT_APPLICABLE
   └─ anything else / empty         → UNSUPPORTED / EMPTY
```

### CRS handling

Area and distance are never computed on latitude/longitude degrees (1° of longitude is ~111 km at the
equator and ~0 km at the poles, so "square degrees" mean nothing).

- **Source CRS** is read from the file (`.prj` for Shapefile; WGS84 for KML) and reported as `EPSG:xxxx` when it can be identified.
- Everything is normalised to WGS84 first, then projected to the **UTM zone of the feature's representative point**
  (`EPSG:326xx` north / `EPSG:327xx` south). Polar features (north of 84°N / south of 80°S, where UTM is undefined)
  use UPS (`EPSG:32661` / `EPSG:32761`).
- The zone is chosen **per feature**, so a file spanning several zones is still measured in each feature's best-fit zone.
- The zone used is returned for each measurement as `projected_crs`, so results are auditable.
- A Shapefile with no CRS is rejected (422) rather than guessed.
- Coordinates outside lon/lat range after conversion (a sign the CRS in the file is wrong) are flagged as `ERROR` for that feature.

**How correctness is verified:** tests compare results with `pyproj.Geod` (true ellipsoidal geodesic area/length)
to within 0.1%, check a 1000 m × 1000 m square in UTM equals exactly 1,000,000 m², and check that the same shape
uploaded in EPSG:32643 and in EPSG:4326 gives the same area. Deliberately removing the projection step makes 7 tests fail.

---

## Design decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| **FastAPI** | Typed request/response models, automatic OpenAPI docs, simple file upload handling. | Django + DRF: more batteries (admin, ORM), but heavier for a small, API-only service. |
| **Synchronous processing** (result is ready when the POST returns) | Parsing and measuring is fast (tens of ms for the samples) and the API contract in the brief (upload → get) is simplest this way. Endpoints are plain `def`, so FastAPI runs them in a thread pool and the event loop isn't blocked. | Background job (Celery/RQ/`BackgroundTasks`) with `PROCESSING` polling. Better for huge files; the `status` field and the `PROCESSING` state are already in place so this is an incremental change. |
| **Projected CRS = UTM zone per feature** | Accurate (distortion well under 0.1% inside a zone), metric, trivially computed from a coordinate, no external lookup. | One CRS for the whole file (simpler, but wrong for files spanning zones). Geodesic calculation with `pyproj.Geod` (most accurate, no zones, but the brief asks for projection; I use it in tests as the independent check). Equal-area projections such as EPSG:6933 (great for area, poor for length). |
| **Always go through WGS84** | One code path for any input CRS; avoids measuring in a CRS that is itself distorted (e.g. Web Mercator inflates areas heavily away from the equator). | Measure directly in the source CRS when it is projected: faster but trusts arbitrary local projections. |
| **GeoPandas/pyogrio (GDAL) for reading** | One reader for Shapefile and KML, handles encodings, `.prj` parsing and KML folders. | `fastkml` + `pyshp`: lighter, but two code paths and more edge cases to maintain. |
| **Store features + measurements in a DB** | `GET` endpoints are cheap, paginated, and survive restarts. Measurements are computed once. | Recompute on every request (no storage, but wasteful and non-paginatable). |
| **SQLite default, SQLAlchemy** | Zero setup for reviewers; switch to Postgres by changing `GEO_DATABASE_URL`. | PostGIS: would enable spatial queries, not needed for this scope. |
| **Unsupported / empty / failing features get a status instead of an error** | The brief asks for graceful handling: one `GeometryCollection` must not make the rest of a 10,000-feature file unusable. | Reject the whole file (loses good data). |
| **Geometry stored in source CRS** | Faithful to the upload; `crs` field says how to interpret it. | Always return WGS84 GeoJSON (spec-compliant GeoJSON, but silently changes the user's data). |
| **One Shapefile per zip** | Avoids ambiguous CRS/feature indexing across layers. | Merge multiple Shapefiles: possible future work. |

### Security notes

- Zip members are **never extracted by archive path** (no zip-slip): only known Shapefile extensions are written, to fixed names inside a temp directory.
- Zip expansion is capped **while streaming**, not by trusting header sizes, and file count is capped (zip bombs).
- Upload size is capped while streaming to disk; the file is never fully loaded in memory.
- Temp files are always removed (`TemporaryDirectory`).

### Known limitations

- `GeometryCollection` / KML `MultiGeometry` features are reported as `UNSUPPORTED` rather than measured part by part.
- Features crossing the antimeridian (±180°) or spanning more than one UTM zone are measured in the zone of their representative point, which is slightly less accurate than a geodesic calculation.
- Z values are discarded; measurements are planimetric (2D).
- `.kmz` and multi-layer Shapefile archives are not accepted.
- No authentication or rate limiting.

---

## Learning

*(Replace with your own words before submitting: interviewers will ask about this.)*

- Why degrees can't be used for area/length, and how UTM zones are derived from longitude/latitude.
- The difference between a *geographic* CRS (EPSG:4326) and a *projected* CRS, and why Web Mercator is a poor choice for measuring.
- How to verify geospatial code: independent geodesic calculations, exact known-answer shapes, and round-trip checks between CRSs.
- Handling untrusted archives safely (zip-slip, decompression bombs) and streaming uploads.
- Designing for partial failure: per-feature status instead of all-or-nothing.

## Future scope

- **Async processing** with a job queue (Celery/RQ + Redis) and progress reporting for very large files; the `PROCESSING` status is already modelled.
- Measure `GeometryCollection` / `MultiGeometry` part by part.
- Geodesic measurement option (`?method=geodesic`) and a choice of output units (ha, acres, km, miles).
- `.kmz`, GeoJSON, GeoPackage and multi-layer archive support.
- PostGIS storage for spatial queries (bounding-box filter, intersects).
- Authentication, per-user files, retention/cleanup of old records, and `DELETE /api/files/{id}/`.
- Alembic migrations, structured logging, metrics, and CI (GitHub Actions running `pytest`).

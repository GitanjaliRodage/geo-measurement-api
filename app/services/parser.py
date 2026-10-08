"""Reads .kml files and zipped Shapefiles into a uniform in-memory structure."""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS
from shapely.geometry.base import BaseGeometry

from app.config import settings
from app.services.crs import WGS84

SHAPEFILE_PARTS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


class ParseError(Exception):
    """The upload is not a usable geospatial file. The message is safe to show to API clients."""


@dataclass
class ParsedFeature:
    index: int
    geometry: BaseGeometry | None  # 2D, in the file's own CRS
    properties: dict


@dataclass
class ParsedFile:
    crs: CRS
    features: list[ParsedFeature]


# --------------------------------------------------------------------------- zip


def extract_shapefile(zip_path: Path, dest: Path) -> Path:
    """Safely extract the single Shapefile inside a zip and return the path to its .shp.

    Safety: members are never extracted under their archive path (no zip-slip), only known
    Shapefile sidecar extensions are written, and total expanded size is capped while
    streaming (declared sizes in a zip header can lie).
    """
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ParseError("The uploaded file is not a valid zip archive.") from exc

    with archive:
        members = [
            (info, PurePosixPath(info.filename.replace("\\", "/")))
            for info in archive.infolist()
            if not info.is_dir()
        ]
        # Ignore macOS resource-fork junk.
        members = [
            (i, p) for i, p in members if "__MACOSX" not in p.parts and not p.name.startswith("._")
        ]
        if len(members) > settings.max_zip_members:
            raise ParseError(f"Zip contains too many files (limit {settings.max_zip_members}).")

        shp_members = [(i, p) for i, p in members if p.suffix.lower() == ".shp"]
        if not shp_members:
            raise ParseError("No .shp file found in the zip archive.")
        if len(shp_members) > 1:
            raise ParseError("The zip contains more than one Shapefile; upload one Shapefile per zip.")

        stem = shp_members[0][1].stem.lower()
        budget = settings.max_zip_uncompressed_mb * 1024 * 1024
        written = 0
        for info, path in members:
            ext = path.suffix.lower()
            if path.stem.lower() != stem or ext not in SHAPEFILE_PARTS:
                continue
            # Normalised, flat target name: never derived from archive paths.
            with archive.open(info) as src, open(dest / f"layer{ext}", "wb") as out:
                while chunk := src.read(1024 * 1024):
                    written += len(chunk)
                    if written > budget:
                        raise ParseError("Zip expands to more than the allowed size.")
                    out.write(chunk)

    return dest / "layer.shp"


# ----------------------------------------------------------------------- reading


def _properties(gdf: gpd.GeoDataFrame) -> list[dict]:
    """Attribute rows as plain JSON-safe dicts (handles NaN, numpy types, timestamps)."""
    attrs = pd.DataFrame(gdf.drop(columns=gdf.geometry.name))
    if attrs.shape[1] == 0:
        return [{} for _ in range(len(gdf))]
    return json.loads(attrs.to_json(orient="records", date_format="iso", default_handler=str))


def _to_parsed(gdf: gpd.GeoDataFrame) -> list[ParsedFeature]:
    props = _properties(gdf)
    features = []
    for i, geom in enumerate(gdf.geometry):
        if geom is not None:
            geom = shapely.force_2d(geom)  # measurements are planimetric; drop Z/M
        features.append(ParsedFeature(index=i, geometry=geom, properties=props[i]))
    return features


def _read(path: Path, **kwargs) -> gpd.GeoDataFrame:
    try:
        return pyogrio.read_dataframe(path, **kwargs)
    except Exception as exc:  # pyogrio raises DataSourceError / DataLayerError / ValueError
        raise ParseError(f"Could not read geospatial data: {exc}") from exc


def parse_shapefile_zip(zip_path: Path, workdir: Path) -> ParsedFile:
    shp = extract_shapefile(zip_path, workdir)
    gdf = _read(shp)
    if gdf.crs is None:
        raise ParseError(
            "The Shapefile has no coordinate reference system (missing or unreadable .prj). "
            "Measurements cannot be computed reliably without it."
        )
    features = _to_parsed(gdf)
    if not features:
        raise ParseError("The Shapefile contains no features.")
    return ParsedFile(crs=gdf.crs, features=features)


def parse_kml(kml_path: Path) -> ParsedFile:
    # KML mandates WGS84 lon/lat. Every Folder becomes a GDAL layer; read them all.
    try:
        layers = [name for name, _ in pyogrio.list_layers(kml_path)]
    except Exception as exc:
        raise ParseError(f"Could not read KML: {exc}") from exc

    frames = []
    for layer in layers:
        gdf = _read(kml_path, layer=layer)
        if len(gdf):
            frames.append(gdf)
    if not frames:
        raise ParseError("The KML file contains no features.")

    combined = pd.concat(frames, ignore_index=True)
    combined = gpd.GeoDataFrame(combined, geometry=frames[0].geometry.name, crs=WGS84)
    return ParsedFile(crs=WGS84, features=_to_parsed(combined))


def parse_upload(path: Path, source_format: str, workdir: Path) -> ParsedFile:
    if source_format == "shapefile":
        return parse_shapefile_zip(path, workdir)
    if source_format == "kml":
        return parse_kml(path)
    raise ParseError(f"Unsupported format '{source_format}'.")


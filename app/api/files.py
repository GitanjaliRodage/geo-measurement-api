import logging
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Feature, FileStatus, UploadedFile
from app.schemas import (
    FeatureOut,
    FeaturesPage,
    FileOut,
    MeasurementOut,
    MeasurementsPage,
    MeasurementSummary,
)
from app.services.ingest import ingest
from app.services.parser import ParseError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])

EXTENSIONS = {".zip": "shapefile", ".kml": "kml"}
CHUNK = 1024 * 1024


# ----------------------------------------------------------------------- helpers


def _save_upload(upload: UploadFile, dest: Path) -> None:
    """Stream the upload to disk, enforcing the size limit without loading it in memory."""
    limit = settings.max_upload_mb * 1024 * 1024
    size = 0
    with open(dest, "wb") as out:
        while chunk := upload.file.read(CHUNK):
            size += len(chunk)
            if size > limit:
                raise HTTPException(413, f"File exceeds the {settings.max_upload_mb} MB upload limit.")
            out.write(chunk)


def _get_file(db: Session, file_id: str) -> UploadedFile:
    record = db.get(UploadedFile, file_id)
    if record is None:
        raise HTTPException(404, "File not found.")
    return record


def _require_completed(record: UploadedFile) -> None:
    if record.status != FileStatus.COMPLETED:
        raise HTTPException(
            409, f"File is {record.status}; results are only available for COMPLETED files."
        )


def _file_out(db: Session, record: UploadedFile) -> FileOut:
    rows = db.execute(
        select(Feature.geometry_type, func.count())
        .where(Feature.file_id == record.id)
        .group_by(Feature.geometry_type)
    ).all()
    return FileOut(
        id=record.id,
        filename=record.filename,
        source_format=record.source_format,
        status=record.status,
        crs=record.crs,
        feature_count=record.feature_count,
        geometry_types={(gtype or "NONE"): n for gtype, n in rows},
        error_message=record.error_message,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


def _mark_failed(db: Session, file_id: str, message: str) -> None:
    db.rollback()
    record = db.get(UploadedFile, file_id)
    record.status = FileStatus.FAILED
    record.error_message = message
    db.commit()


# --------------------------------------------------------------------- endpoints


@router.post("/", response_model=FileOut, status_code=201, summary="Upload and process a file")
def upload_file(file: UploadFile, db: Session = Depends(get_db)):
    """Upload a `.kml` or a `.zip` containing one Shapefile.

    The file is parsed and measured synchronously; on success the response already has
    status `COMPLETED`. Unreadable files return 422 and are recorded with status `FAILED`.
    """
    filename = Path(file.filename or "").name
    ext = Path(filename).suffix.lower()
    if ext not in EXTENSIONS:
        raise HTTPException(415, "Unsupported file type. Upload a .kml file or a .zip containing a Shapefile.")

    with tempfile.TemporaryDirectory(prefix="geo_upload_") as tmp:
        workdir = Path(tmp)
        saved = workdir / f"upload{ext}"
        _save_upload(file, saved)

        record = UploadedFile(
            id=uuid.uuid4().hex, filename=filename, source_format=EXTENSIONS[ext], status=FileStatus.PROCESSING
        )
        db.add(record)
        db.commit()
        file_id = record.id

        try:
            record = ingest(db, record, saved, workdir)
        except ParseError as exc:
            _mark_failed(db, file_id, str(exc))
            raise HTTPException(422, detail={"id": file_id, "status": FileStatus.FAILED, "message": str(exc)})
        except Exception:
            log.exception("Unexpected error while processing %s", filename)
            _mark_failed(db, file_id, "Internal error while processing the file.")
            raise HTTPException(500, detail={"id": file_id, "status": FileStatus.FAILED,
                                             "message": "Internal error while processing the file."})

    return _file_out(db, record)


@router.get("/{file_id}/", response_model=FileOut, summary="File information")
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _file_out(db, _get_file(db, file_id))


@router.get("/{file_id}/features/", response_model=FeaturesPage, summary="Features with geometry and properties")
def get_features(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file(db, file_id)
    _require_completed(record)
    features = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.feature_index).offset(offset).limit(limit)
    ).all()
    return FeaturesPage(
        file_id=file_id,
        total=record.feature_count,
        limit=limit,
        offset=offset,
        features=[FeatureOut.model_validate(f) for f in features],
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementsPage, summary="Measurements for every feature")
def get_measurements(
    file_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    record = _get_file(db, file_id)
    _require_completed(record)

    page = db.scalars(
        select(Feature).where(Feature.file_id == file_id).order_by(Feature.feature_index).offset(offset).limit(limit)
    ).all()

    total_area, total_length = db.execute(
        select(func.coalesce(func.sum(Feature.area_sq_m), 0.0), func.coalesce(func.sum(Feature.length_m), 0.0)).where(
            Feature.file_id == file_id
        )
    ).one()
    status_counts = dict(
        db.execute(
            select(Feature.measurement_status, func.count())
            .where(Feature.file_id == file_id)
            .group_by(Feature.measurement_status)
        ).all()
    )

    return MeasurementsPage(
        file_id=file_id,
        crs=record.crs,
        total=record.feature_count,
        limit=limit,
        offset=offset,
        summary=MeasurementSummary(
            total_area_sq_m=round(total_area, 4), total_length_m=round(total_length, 4), status_counts=status_counts
        ),
        measurements=[MeasurementOut.from_feature(f) for f in page],
    )

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.files import router as files_router
from app.database import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    description="Upload a Shapefile (.zip) or KML and get per-feature area and length measurements.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(files_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}

import json
import math
import threading
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from soybean_app.services import *
from soybean_app.services.hermes import *
from .common import *

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    stats_error = ""
    stats = empty_home_ptm_stats()
    today = date.today()
    home_visit_count = "-"

    try:
        stats = get_cached_home_ptm_stats()
    except Exception:
        stats_error = "PTM statistics are temporarily unavailable. Please check database connection."

    try:
        visit_count = increment_home_visit_count()
        if visit_count is not None:
            home_visit_count = _format_int(visit_count)
    except Exception:
        home_visit_count = "-"

    return render_template(
        request,
        "home.html",
        title="Home",
        active="home",
        extra_context={
            "stats": stats,
            "stats_error": stats_error,
            "site_today": today.isoformat(),
            "site_year": today.year,
            "home_visit_count": home_visit_count,
        },
    )


@router.get("/admin/refresh-home-stats")
async def refresh_home_stats() -> dict[str, Any]:
    stats = refresh_home_ptm_stats_cache()
    return {
        "status": "ok",
        "total_sites": stats.get("total_sites", 0),
        "total_proteins": stats.get("total_proteins", 0),
    }


@router.get("/downloads/import-ready/{filename}")
async def download_import_ready(request: Request, filename: str) -> FileResponse:
    _require_downloads_enabled(request)
    allowed = {str(item["filename"]) for item in HOME_DATA_TABLES}
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="File not found")
    path = IMPORT_READY_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path,
        media_type="text/csv",
        filename=filename,
    )




@router.get("/downloads/protein-sites.csv")
async def download_protein_sites(
    request: Request,
    identifier: str = Query(default="", alias="identifier"),
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
) -> Response:
    _require_downloads_enabled(request)
    selected_species = normalize_species_key(species)
    clean_identifier = identifier.strip()
    if not clean_identifier:
        raise HTTPException(status_code=400, detail="Missing identifier")

    rows, filename_key = build_site_download_rows(clean_identifier, selected_species)
    if not rows:
        raise HTTPException(status_code=404, detail="No PTM sites found")
    filename = f"protein-sites-{_safe_download_name(filename_key)}.csv"
    return _csv_response(filename, SITE_DOWNLOAD_HEADERS, rows)


@router.get("/downloads/protein-sites-batch.csv")
async def download_protein_sites_batch(
    request: Request,
    identifiers: str = Query(default="", alias="identifiers"),
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
) -> Response:
    return _protein_sites_batch_response(request, identifiers, species)


@router.post("/downloads/protein-sites-batch.csv")
async def download_protein_sites_batch_post(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
) -> Response:
    payload = payload or {}
    return _protein_sites_batch_response(
        request,
        payload.get("identifiers", ""),
        str(payload.get("species", DEFAULT_SPECIES) or DEFAULT_SPECIES),
    )


@router.get("/downloads/protein-download-all.xlsx")
async def download_protein_all(
    request: Request,
    identifiers: str = Query(default="", alias="identifiers"),
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
) -> Response:
    return _protein_download_all_response(request, identifiers, species)


@router.post("/downloads/protein-download-all.xlsx")
async def download_protein_all_post(
    request: Request,
    payload: dict[str, Any] | None = Body(default=None),
) -> Response:
    payload = payload or {}
    return _protein_download_all_response(
        request,
        payload.get("identifiers", ""),
        str(payload.get("species", DEFAULT_SPECIES) or DEFAULT_SPECIES),
    )


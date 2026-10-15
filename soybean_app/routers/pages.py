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


@router.get("/analysis", response_class=HTMLResponse)
async def analysis(request: Request) -> HTMLResponse:
    return render_page(request, "analysis", "analysis")


@router.get("/browse", response_class=HTMLResponse)
async def browse(request: Request) -> HTMLResponse:
    return render_page(request, "browse", "browse")


@router.get("/data/raw", response_class=HTMLResponse)
async def raw_data(request: Request) -> HTMLResponse:
    downloads_allowed = current_downloads_enabled(request)
    return render_template(
        request,
        "raw_data.html",
        title="Raw Data",
        active="data-raw",
        extra_context={"home_data_tables": _build_home_data_tables(downloads_allowed)},
    )


@router.get("/data/table", response_class=HTMLResponse)
async def data_table(
    request: Request,
    dataset: str = Query(default="soybean_gs", alias="dataset"),
    page: int = Query(default=1, alias="page"),
    page_size: int = Query(default=DATA_TABLE_PAGE_SIZE_DEFAULT, alias="page_size"),
) -> HTMLResponse:
    _require_downloads_enabled(request)
    selected_page_size = page_size if page_size in DATA_TABLE_PAGE_SIZE_OPTIONS else DATA_TABLE_PAGE_SIZE_DEFAULT
    selected_page = max(1, page)
    config = _get_data_table_config(dataset)
    message = ""
    headers: list[str] = []
    rows: list[list[str]] = []
    total_rows = 0
    table_meta: dict[str, Any] = {
        "dataset": dataset,
        "filename": "",
        "species": "",
        "data_type": "",
        "download_url": "",
    }

    if config is None:
        message = "Unknown dataset."
    else:
        filename = str(config["filename"])
        path = IMPORT_READY_DIR / filename
        table_meta = {
            "dataset": str(config["dataset"]),
            "filename": filename,
            "species": str(config["species"]),
            "data_type": str(config["data_type"]),
            "download_url": f"/downloads/import-ready/{urllib.parse.quote(filename)}" if current_downloads_enabled(request) else "",
        }
        if not path.exists() or not path.is_file():
            message = "Dataset file is missing."
        else:
            try:
                headers, rows, total_rows = _read_csv_page(path, selected_page, selected_page_size)
            except Exception:
                message = "Unable to read dataset CSV."

    total_pages = max(1, math.ceil(total_rows / selected_page_size)) if total_rows > 0 else 1
    selected_page = _clamp_int(selected_page, 1, total_pages)
    if total_rows > 0 and rows == [] and not message:
        config_path = IMPORT_READY_DIR / str(config["filename"]) if config else Path()
        headers, rows, total_rows = _read_csv_page(config_path, selected_page, selected_page_size)

    page_meta = {
        "total_rows": total_rows,
        "total_pages": total_pages,
        "current_page": selected_page,
        "page_size": selected_page_size,
        "start_row": 0 if total_rows == 0 else ((selected_page - 1) * selected_page_size) + 1,
        "end_row": min(selected_page * selected_page_size, total_rows),
        "prev_page": selected_page - 1 if selected_page > 1 else 1,
        "next_page": selected_page + 1 if selected_page < total_pages else total_pages,
    }

    return render_template(
        request,
        "data_table.html",
        title="Data Table",
        active="data-raw",
        extra_context={
            "home_data_tables": _build_home_data_tables(current_downloads_enabled(request)),
            "table_meta": table_meta,
            "headers": headers,
            "rows": rows,
            "page_meta": page_meta,
            "page_size_options": DATA_TABLE_PAGE_SIZE_OPTIONS,
            "message": message,
        },
    )


@router.get("/data/submit", response_class=HTMLResponse)
async def submit_data(request: Request) -> HTMLResponse:
    return render_page(request, "data-submit", "data-submit")


@router.get("/submit-data", response_class=HTMLResponse)
async def submit_data_legacy(request: Request) -> HTMLResponse:
    return render_page(request, "data-submit", "data-submit")


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request) -> HTMLResponse:
    return render_page(request, "about", "about")

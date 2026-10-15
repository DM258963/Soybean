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


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request) -> RedirectResponse:
    return RedirectResponse(url="/proteome", status_code=302)


@router.get("/proteome", response_class=HTMLResponse)
async def proteome_search(
    request: Request,
    tab: str = Query(default="identifier"),
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    gene_name: str = Query(default="", alias="gene_name"),
    sequence: str = Query(default="", alias="sequence"),
    identity_min: float = Query(default=BLAST_DEFAULT_IDENTITY_MIN, alias="identity_min"),
    e_value_max: float = Query(default=BLAST_DEFAULT_E_VALUE_MAX, alias="e_value_max"),
    query_cover_min: float = Query(default=BLAST_DEFAULT_QUERY_COVER_MIN, alias="query_cover_min"),
    max_hits: int = Query(default=BLAST_DEFAULT_MAX_HITS, alias="max_hits"),
) -> HTMLResponse:
    search_tab = tab.strip().lower() or "identifier"
    if search_tab not in {"identifier", "sequence"}:
        search_tab = "identifier"
    selected_species = normalize_species_key(species)
    selected_species_label = str(get_species_option(selected_species).get("display", selected_species))
    selected_identity_min = _clamp_float(identity_min, 0, 100)
    selected_e_value_max = _clamp_float(e_value_max, 0, 1000)
    selected_query_cover_min = _clamp_float(query_cover_min, 0, 100)
    selected_max_hits = _clamp_int(max_hits, 5, 100)

    gene_query = gene_name.strip()
    sequence_query = sequence.strip()
    normalized_sequence_query = normalize_sequence_input(sequence_query)
    proteome_rows: list[dict[str, Any]] = []
    sequence_blast_summary = {
        "candidate_count": 0,
        "query_length": len(normalized_sequence_query),
        "matched_hits": 0,
        "identity_min": selected_identity_min,
        "e_value_max": selected_e_value_max,
        "query_cover_min": selected_query_cover_min,
    }
    message = ""

    if search_tab == "identifier" and gene_query:
        try:
            proteome_rows = search_expression_records(gene_query, selected_species)
            if proteome_rows:
                expression_count = sum(1 for row in proteome_rows if row.get("has_expression"))
                if expression_count == len(proteome_rows):
                    message = f"Found {len(proteome_rows)} protein expression profile rows in {selected_species_label}."
                else:
                    message = (
                        f"Found {len(proteome_rows)} protein rows in {selected_species_label}; "
                        f"{expression_count} have quantitative expression profiles."
                    )
            else:
                message = f'No expression profile found for "{gene_query}" in {selected_species_label}.'
        except Exception:
            message = "Expression profile query failed. Please check the expression dataset files."

    if search_tab == "sequence" and sequence_query:
        try:
            if len(normalized_sequence_query) < 10:
                message = "Sequence is too short. Please input at least 10 amino acids for BLAST search."
            else:
                blast_rows, sequence_blast_summary = build_blast_summary_rows(
                    normalized_sequence_query,
                    species=selected_species,
                    max_hits=selected_max_hits,
                    identity_min=selected_identity_min,
                    e_value_max=selected_e_value_max,
                    query_cover_min=selected_query_cover_min,
                )
                proteome_rows = build_proteome_blast_rows(blast_rows, selected_species)
                if proteome_rows:
                    message = (
                        f"Found {len(proteome_rows)} BLAST hits in {selected_species_label}. "
                        "Proteins without quantitative expression data are shown as NA."
                    )
                else:
                    message = f"No BLAST hits passed the selected thresholds in {selected_species_label}."
        except Exception as exc:
            message = f"BLAST query failed: {exc}"

    return render_template(
        request,
        "proteome_search.html",
        title="Protein Expression Profiles",
        active="proteome",
        extra_context={
            "search_tab": search_tab,
            "species_options": SPECIES_OPTIONS,
            "selected_species": selected_species,
            "selected_species_label": selected_species_label,
            "gene_query": gene_query,
            "sequence_query": sequence_query,
            "proteome_rows": proteome_rows,
            "expression_timepoints": EXPRESSION_TIMEPOINTS,
            "sequence_blast_summary": sequence_blast_summary,
            "blast_identity_min": selected_identity_min,
            "blast_e_value_max": selected_e_value_max,
            "blast_query_cover_min": selected_query_cover_min,
            "blast_max_hits": selected_max_hits,
            "message": message,
        },
    )


@router.get("/proteome/detail", response_class=HTMLResponse)
async def proteome_detail(
    request: Request,
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    identifier: str = Query(default="", alias="identifier"),
    return_tab: str = Query(default="identifier", alias="return_tab"),
    return_query: str = Query(default="", alias="return_query"),
) -> HTMLResponse:
    selected_species = normalize_species_key(species)
    clean_identifier = identifier.strip()
    detail = build_proteome_detail(clean_identifier, selected_species) if clean_identifier else {
        "profile": {},
        "meta": {},
        "replicate_rows": [],
    }
    message = "" if detail.get("profile", {}).get("available") else "No quantitative expression data matched this protein accession."

    return render_template(
        request,
        "proteome_detail.html",
        title="Protein Expression Profile",
        active="proteome",
        extra_context={
            "selected_species": selected_species,
            "selected_species_label": str(get_species_option(selected_species).get("display", selected_species)),
            "identifier": clean_identifier,
            "return_tab": return_tab,
            "return_query": return_query,
            "expression_profile": detail.get("profile", {}),
            "expression_meta": detail.get("meta", {}),
            "replicate_rows": detail.get("replicate_rows", []),
            "message": message,
        },
    )


@router.get("/search/protein", response_class=HTMLResponse)
async def search_protein(
    request: Request,
    tab: str = Query(default="identifier"),
    view: str = Query(default="overview", alias="view"),
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    gene_name: str = Query(default="", alias="gene_name"),
    return_gene_name: str = Query(default="", alias="return_gene_name"),
    sequence: str = Query(default="", alias="sequence"),
    identity_min: float = Query(default=BLAST_DEFAULT_IDENTITY_MIN, alias="identity_min"),
    e_value_max: float = Query(default=BLAST_DEFAULT_E_VALUE_MAX, alias="e_value_max"),
    query_cover_min: float = Query(default=BLAST_DEFAULT_QUERY_COVER_MIN, alias="query_cover_min"),
    max_hits: int = Query(default=BLAST_DEFAULT_MAX_HITS, alias="max_hits"),
) -> HTMLResponse:
    search_tab = tab.strip().lower() or "identifier"
    if search_tab not in {"identifier", "sequence"}:
        search_tab = "identifier"
    result_view = view.strip().lower() or "overview"
    if result_view not in {"overview", "detail"}:
        result_view = "overview"
    selected_species = normalize_species_key(species)
    selected_species_label = str(get_species_option(selected_species).get("display", selected_species))
    selected_identity_min = _clamp_float(identity_min, 0, 100)
    selected_e_value_max = _clamp_float(e_value_max, 0, 1000)
    selected_query_cover_min = _clamp_float(query_cover_min, 0, 100)
    selected_max_hits = _clamp_int(max_hits, 5, 100)

    gene_query = gene_name.strip()
    return_gene_query = return_gene_name.strip()
    sequence_query = sequence.strip()
    normalized_sequence_query = normalize_sequence_input(sequence_query)

    result_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    legend_items: list[dict[str, str]] = []
    result_meta: dict[str, Any] = {}
    site_chart_data: list[dict[str, Any]] = []
    site_chart_default_id = ""
    protein_ptm_map: dict[str, Any] = {}
    expression_profile: dict[str, Any] = {}
    sequence_length = 0
    protein_sequence_export = ""
    message = ""
    identifier_match_rows: list[dict[str, Any]] = []
    show_identifier_match_table = False
    identifier_tokens = split_identifier_query(gene_query) if search_tab == "identifier" else []
    batch_summary_rows: list[dict[str, Any]] = []
    batch_download_identifiers = ""
    show_batch_summary_table = False
    sequence_blast_rows: list[dict[str, Any]] = []
    sequence_blast_summary = {
        "candidate_count": 0,
        "query_length": len(normalized_sequence_query),
        "matched_hits": 0,
        "identity_min": selected_identity_min,
        "e_value_max": selected_e_value_max,
        "query_cover_min": selected_query_cover_min,
    }

    if search_tab == "identifier" and gene_query:
        try:
            if result_view != "detail":
                tokens_for_overview = identifier_tokens if identifier_tokens else [gene_query]
                batch_summary_rows = build_protein_summary_rows(tokens_for_overview, selected_species)
                show_batch_summary_table = True
                batch_download_identifiers = "\n".join(
                    str(row.get("select_key", "")).strip()
                    for row in batch_summary_rows
                    if row.get("has_result") and str(row.get("select_key", "")).strip()
                )
                matched_count = sum(1 for row in batch_summary_rows if row.get("has_result"))
                if matched_count:
                    message = (
                        f"Found {matched_count} matched protein overview rows from {len(tokens_for_overview)} submitted IDs. "
                        "Open a row to view detailed PTM sites."
                    )
                else:
                    message = f'No result found for "{gene_query}" in {selected_species_label}. Please try another identifier.'
                matched_rows = []
            else:
                matched_rows = fetch_sites_for_identifier(identifier_tokens[0] if identifier_tokens else gene_query, selected_species)

            if show_batch_summary_table:
                pass
            elif not matched_rows:
                message = f'No result found for "{gene_query}" in {selected_species_label}. Please try another Gene name.'
            else:
                identifier_match_rows = build_identifier_match_rows(matched_rows, gene_query)
                has_exact = any(bool(item.get("is_exact")) for item in identifier_match_rows)

                if not has_exact and len(identifier_match_rows) > 1:
                    show_identifier_match_table = True
                    message = (
                        f'Found {len(identifier_match_rows)} matches for "{gene_query}". '
                        "Please choose one row to view details."
                    )
                else:
                    selected_key = identifier_match_rows[0].get("select_key", "") if identifier_match_rows else gene_query
                    selected_rows = fetch_sites_for_identifier(str(selected_key), selected_species)
                    selected_rows = keep_primary_target_rows(selected_rows)

                    result_rows, result_meta = build_result_rows_and_meta(selected_rows)
                    if result_rows:
                        site_chart_data = build_site_chart_data(result_rows)
                        site_chart_default_id = str(result_rows[0].get("Site id", ""))
                        expression_profile = build_expression_profile(
                            str(result_meta.get("protein_accession", "")),
                            selected_species,
                        )
                        linked_sequence = fetch_protein_sequence_by_identifiers(
                            collect_identifier_tokens(
                                result_meta.get("gene_name", ""),
                                result_meta.get("protein_accession", ""),
                                result_meta.get("gene_names", ""),
                                result_meta.get("transcript_id", ""),
                                result_meta.get("protein_description", ""),
                            )
                        )
                        protein_sequence_export = linked_sequence
                        sequence_length = len(linked_sequence)
                        sequence_rows = build_sequence_rows(linked_sequence, result_rows)
                        protein_ptm_map = build_protein_ptm_map(linked_sequence, result_rows, result_meta)
                        legend_items = build_ptm_legend_from_sequence(sequence_rows)
                        if not sequence_rows:
                            message = (
                                "Matched GS PTM sites were found, but no linked protein sequence was found "
                                "in ptm.protein_sequence for this Gene name."
                            )
                    else:
                        message = f'No valid PTM position found for "{gene_query}".'
        except Exception:
            message = "Database query failed. Please check Docker/PostgreSQL status and imported data."

    if search_tab == "sequence" and sequence_query:
        try:
            if len(normalized_sequence_query) < 10:
                message = "Sequence is too short. Please input at least 10 amino acids for BLAST search."
            else:
                sequence_blast_rows, sequence_blast_summary = build_blast_summary_rows(
                    normalized_sequence_query,
                    species=selected_species,
                    max_hits=selected_max_hits,
                    identity_min=selected_identity_min,
                    e_value_max=selected_e_value_max,
                    query_cover_min=selected_query_cover_min,
                )
                if sequence_blast_rows:
                    message = (
                        f"Found {len(sequence_blast_rows)} BLAST hits in {selected_species_label}. "
                        "Proteins without PTM annotation are retained with #PTMs shown as 0."
                    )
                else:
                    message = f"No BLAST hits passed the selected thresholds in {selected_species_label}."
        except Exception as exc:
            message = f"BLAST query failed: {exc}"

    return render_template(
        request,
        "protein_search.html",
        title="Protein Search",
        active="search-protein",
        extra_context={
            "search_tab": search_tab,
            "result_view": result_view,
            "species_options": SPECIES_OPTIONS,
            "selected_species": selected_species,
            "selected_species_label": selected_species_label,
            "species_identifier_examples": SPECIES_IDENTIFIER_EXAMPLES,
            "gene_query": gene_query,
            "return_gene_query": return_gene_query,
            "sequence_query": sequence_query,
            "result_rows": result_rows,
            "sequence_rows": sequence_rows,
            "legend_items": legend_items,
            "result_meta": result_meta,
            "site_chart_data_json": json.dumps(site_chart_data, ensure_ascii=False),
            "site_chart_default_id": site_chart_default_id,
            "protein_ptm_map": protein_ptm_map,
            "expression_profile": expression_profile,
            "sequence_length": sequence_length,
            "protein_sequence_export": protein_sequence_export,
            "message": message,
            "identifier_match_rows": identifier_match_rows,
            "show_identifier_match_table": show_identifier_match_table,
            "identifier_tokens": identifier_tokens,
            "batch_summary_rows": batch_summary_rows,
            "batch_download_identifiers": batch_download_identifiers,
            "show_batch_summary_table": show_batch_summary_table,
            "sequence_blast_rows": sequence_blast_rows,
            "sequence_blast_summary": sequence_blast_summary,
            "blast_identity_min": selected_identity_min,
            "blast_e_value_max": selected_e_value_max,
            "blast_query_cover_min": selected_query_cover_min,
            "blast_max_hits": selected_max_hits,
        },
    )


@router.get("/search/ptm", response_class=HTMLResponse)
async def search_ptm(
    request: Request,
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    expression: str = Query(default="", alias="expression"),
    sequence_length: int = Query(default=10, alias="sequence_length"),
    page: int = Query(default=1, alias="page"),
    page_size: int = Query(default=PTM_SEARCH_PAGE_SIZE_DEFAULT, alias="page_size"),
) -> HTMLResponse:
    selected_species = normalize_species_key(species)
    selected_species_label = str(get_species_option(selected_species).get("display", selected_species))
    expression_query = expression.strip()
    query_params = request.query_params
    if "representative_only_present" in query_params:
        representative_only = "representative_only" in query_params
    else:
        representative_only = True
    peptides_unique = _query_checkbox_checked(query_params, "peptides_unique", default=False)
    flank_length = _clamp_int(sequence_length, 3, 30)
    selected_page_size = page_size if page_size in PTM_SEARCH_PAGE_SIZE_OPTIONS else PTM_SEARCH_PAGE_SIZE_DEFAULT
    selected_page = max(1, page)

    result_rows: list[dict[str, Any]] = []
    grouped_rows: list[dict[str, Any]] = []
    summary = {"matched_proteins": 0, "matched_sites": 0, "truncated": 0}
    page_meta = {
        "total_rows": 0,
        "total_pages": 1,
        "current_page": 1,
        "page_size": selected_page_size,
        "start_row": 0,
        "end_row": 0,
        "prev_page": 1,
        "next_page": 1,
    }
    message = ""

    if expression_query:
        parsed, parse_error = parse_ptm_search_expression(expression_query)
        if parse_error:
            message = parse_error
        else:
            try:
                raw_matches, summary = run_ptm_expression_search(
                    parsed,
                    sequence_length=flank_length,
                    representative_only=representative_only,
                    peptides_unique=peptides_unique,
                    max_results=PTM_SEARCH_MAX_RESULTS,
                    species=selected_species,
                )

                all_site_rows = build_ptm_site_rows(raw_matches)
                result_rows, page_meta = paginate_rows(all_site_rows, selected_page, selected_page_size)
                grouped_rows = group_ptm_rows_by_protein(result_rows)

                if not all_site_rows:
                    message = f'No records matched "{expression_query}" in {selected_species_label}.'
                elif summary["truncated"]:
                    message = (
                        f"Result set is large. Showing up to {PTM_SEARCH_MAX_RESULTS} matches before pagination. "
                        "Refine expression for narrower results."
                    )
            except Exception:
                message = "PTM query failed. Please check Docker/PostgreSQL status and imported data."
    elif query_params:
        message = "Please enter a Search Expression."

    return render_template(
        request,
        "ptm_search.html",
        title="PTM Search",
        active="search-ptm",
        extra_context={
            "expression_query": expression_query,
            "species_options": SPECIES_OPTIONS,
            "selected_species": selected_species,
            "selected_species_label": selected_species_label,
            "sequence_length": flank_length,
            "representative_only": representative_only,
            "peptides_unique": peptides_unique,
            "fixed_species": selected_species_label,
            "result_rows": result_rows,
            "grouped_rows": grouped_rows,
            "summary": summary,
            "page_meta": page_meta,
            "message": message,
            "ptm_reference_rows": _build_ptm_reference_rows(),
            "max_results": PTM_SEARCH_MAX_RESULTS,
            "page_size_options": PTM_SEARCH_PAGE_SIZE_OPTIONS,
        },
    )


@router.get("/search/blast", response_class=HTMLResponse)
async def search_blast(
    request: Request,
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    sequence: str = Query(default="", alias="sequence"),
    max_hits: int = Query(default=BLAST_DEFAULT_MAX_HITS, alias="max_hits"),
) -> RedirectResponse:
    selected_species = normalize_species_key(species)
    sequence_query = sequence.strip()
    selected_max_hits = _clamp_int(max_hits, 5, 100)
    params = {
        "tab": "sequence",
        "species": selected_species,
        "max_hits": str(selected_max_hits),
        "identity_min": str(BLAST_DEFAULT_IDENTITY_MIN),
        "e_value_max": str(BLAST_DEFAULT_E_VALUE_MAX),
        "query_cover_min": str(BLAST_DEFAULT_QUERY_COVER_MIN),
    }
    if sequence_query:
        params["sequence"] = sequence_query
    return RedirectResponse(
        url=f"{request.url_for('search_protein')}?{urllib.parse.urlencode(params)}",
        status_code=302,
    )


@router.get("/search/blast/detail", response_class=HTMLResponse)
async def search_blast_detail(
    request: Request,
    species: str = Query(default=DEFAULT_SPECIES, alias="species"),
    identifier: str = Query(default="", alias="identifier"),
    sequence: str = Query(default="", alias="sequence"),
    max_hits: int = Query(default=BLAST_DEFAULT_MAX_HITS, alias="max_hits"),
    identity_min: float = Query(default=BLAST_DEFAULT_IDENTITY_MIN, alias="identity_min"),
    e_value_max: float = Query(default=BLAST_DEFAULT_E_VALUE_MAX, alias="e_value_max"),
    query_cover_min: float = Query(default=BLAST_DEFAULT_QUERY_COVER_MIN, alias="query_cover_min"),
) -> HTMLResponse:
    selected_species = normalize_species_key(species)
    clean_identifier = identifier.strip()
    sequence_query = sequence.strip()
    selected_max_hits = _clamp_int(max_hits, 5, 100)
    selected_identity_min = _clamp_float(identity_min, 0, 100)
    selected_e_value_max = _clamp_float(e_value_max, 0, 1000)
    selected_query_cover_min = _clamp_float(query_cover_min, 0, 100)
    result_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    legend_items: list[dict[str, str]] = []
    result_meta: dict[str, Any] = {}
    site_chart_data: list[dict[str, Any]] = []
    site_chart_default_id = ""
    protein_ptm_map: dict[str, Any] = {}
    expression_profile: dict[str, Any] = {}
    sequence_length = 0
    protein_sequence_export = ""
    message = ""

    if not clean_identifier:
        message = "Missing BLAST hit identifier."
    else:
        try:
            matched_rows = fetch_sites_for_identifier(clean_identifier, selected_species)
            matched_rows = keep_primary_target_rows(matched_rows)
            result_rows, result_meta = build_result_rows_and_meta(matched_rows)
            if not result_rows:
                message = f'No PTM details found for "{clean_identifier}".'
            else:
                site_chart_data = build_site_chart_data(result_rows)
                site_chart_default_id = str(result_rows[0].get("Site id", ""))
                expression_profile = build_expression_profile(
                    str(result_meta.get("protein_accession", "")),
                    selected_species,
                )
                linked_sequence = fetch_protein_sequence_by_identifiers(
                    collect_identifier_tokens(
                        result_meta.get("gene_name", ""),
                        result_meta.get("protein_accession", ""),
                        result_meta.get("gene_names", ""),
                        result_meta.get("transcript_id", ""),
                        result_meta.get("protein_description", ""),
                    )
                )
                protein_sequence_export = linked_sequence
                sequence_length = len(linked_sequence)
                sequence_rows = build_sequence_rows(linked_sequence, result_rows)
                protein_ptm_map = build_protein_ptm_map(linked_sequence, result_rows, result_meta)
                legend_items = build_ptm_legend_from_sequence(sequence_rows)
                if not sequence_rows:
                    message = (
                        "Matched PTM sites were found, but no linked protein sequence was found "
                        "in ptm.protein_sequence for this Gene name."
                    )
        except Exception:
            message = "BLAST hit detail query failed. Please check Docker/PostgreSQL status and imported data."

    return render_template(
        request,
        "blast_detail.html",
        title="BLAST Hit Details",
        active="search-protein",
        extra_context={
            "selected_species": selected_species,
            "identifier": clean_identifier,
            "sequence_query": sequence_query,
            "max_hits": selected_max_hits,
            "identity_min": selected_identity_min,
            "e_value_max": selected_e_value_max,
            "query_cover_min": selected_query_cover_min,
            "result_rows": result_rows,
            "sequence_rows": sequence_rows,
            "legend_items": legend_items,
            "result_meta": result_meta,
            "site_chart_data_json": json.dumps(site_chart_data, ensure_ascii=False),
            "site_chart_default_id": site_chart_default_id,
            "protein_ptm_map": protein_ptm_map,
            "expression_profile": expression_profile,
            "sequence_length": sequence_length,
            "protein_sequence_export": protein_sequence_export,
            "message": message,
        },
    )

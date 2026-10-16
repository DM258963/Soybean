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


@router.get("/api/hermes/schema")
async def hermes_schema() -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    return {
        "ok": True,
        "name": "Soybean PTM Viewer Hermes Tools",
        "version": "1.0",
        "assistant_enabled": HERMES_ASSISTANT_ENABLED,
        "chat_provider": HERMES_CHAT_PROVIDER,
        "chat_model": HERMES_CHAT_MODEL,
        "agent": {
            "file": str(HERMES_AGENT_FILE.relative_to(BASE_DIR)) if HERMES_AGENT_FILE.exists() else "",
            "skills": [str(path.relative_to(BASE_DIR)) for path in _hermes_skill_paths()],
        },
        "species_options": SPECIES_OPTIONS,
        "default_species": DEFAULT_SPECIES,
        "tools": [
            {
                "name": "protein_search",
                "endpoint": "/api/hermes/protein",
                "description": "Search protein/PTM overview and PTM site details by gene name, accession, transcript id, or short id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "species": {"type": "string", "enum": [item["value"] for item in SPECIES_OPTIONS]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": HERMES_TOOL_RECORD_LIMIT_MAX},
                        "site_limit": {"type": "integer", "minimum": 1, "maximum": HERMES_TOOL_RECORD_LIMIT_MAX},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ptm_search",
                "endpoint": "/api/hermes/ptm",
                "description": "Search PTM motif/expression patterns using the same parser as the PTM Search page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                        "species": {"type": "string", "enum": [item["value"] for item in SPECIES_OPTIONS]},
                        "sequence_length": {"type": "integer", "minimum": 3, "maximum": 30},
                        "representative_only": {"type": "boolean"},
                        "peptides_unique": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": HERMES_TOOL_RECORD_LIMIT_MAX},
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "blast_search",
                "endpoint": "/api/hermes/blast",
                "description": "Run protein BLAST against cached soybean/rhizobium protein sequences.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sequence": {"type": "string", "maxLength": HERMES_BLAST_SEQUENCE_MAX},
                        "species": {"type": "string", "enum": [item["value"] for item in SPECIES_OPTIONS]},
                        "max_hits": {"type": "integer", "minimum": 5, "maximum": 100},
                        "identity_min": {"type": "number", "minimum": 0, "maximum": 100},
                        "e_value_max": {"type": "number", "minimum": 0, "maximum": 1000},
                        "query_cover_min": {"type": "number", "minimum": 0, "maximum": 100},
                    },
                    "required": ["sequence"],
                },
            },
        ],
    }


@router.post("/api/hermes/query")
async def hermes_query(request: Request, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    try:
        payload = {
            **payload,
            "_allow_multiple_identifiers": current_user_can_search_multiple_identifiers(request),
        }
        user_message = _hermes_payload_text(payload, "message", "query", "text", "identifier", "gene_name", "expression", "sequence")
        result = _hermes_query_payload(payload)
        result["routed_tool"] = result.get("tool")
        if not result.get("answer"):
            if result.get("tool") in {"protein_search", "ptm_search", "blast_search"}:
                result["answer"] = _hermes_compact_answer(result)
            elif result.get("router") == "ollama":
                result["answer"] = _hermes_summarized_answer(user_message, result)
            else:
                result["answer"] = _hermes_compact_answer(result)
        return result
    except ValueError as exc:
        return {"ok": False, "tool": _hermes_detect_tool(payload), "message": str(exc), "answer": str(exc), "records": []}
    except Exception as exc:
        message = f"Hermes query failed: {exc}"
        return {"ok": False, "tool": _hermes_detect_tool(payload), "message": message, "answer": message, "records": []}


@router.get("/api/hermes/evaluate")
async def hermes_evaluate(use_ollama: bool = Query(default=True, alias="use_ollama")) -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    cases: list[dict[str, Any]] = []
    correct_tool = 0
    correct_species = 0
    for idx, case in enumerate(HERMES_ROUTER_TEST_CASES, start=1):
        payload = {"query": str(case["message"])}
        if use_ollama and HERMES_CHAT_ENABLED:
            try:
                route = _hermes_route_with_ollama(str(case["message"]), payload)
            except Exception as exc:
                route = _hermes_route_with_rules(payload)
                route["router_error"] = str(exc)
        else:
            route = _hermes_route_with_rules(payload)
        arguments = route.get("arguments") if isinstance(route.get("arguments"), dict) else {}
        predicted_tool = str(route.get("tool") or "")
        predicted_species = normalize_species_key(str(arguments.get("species") or DEFAULT_SPECIES))
        expected_tool = str(case["expected_tool"])
        expected_species = str(case["expected_species"])
        tool_ok = predicted_tool == expected_tool
        species_ok = predicted_species == expected_species
        correct_tool += 1 if tool_ok else 0
        correct_species += 1 if species_ok else 0
        cases.append(
            {
                "id": idx,
                "message": case["message"],
                "expected_tool": expected_tool,
                "predicted_tool": predicted_tool,
                "tool_ok": tool_ok,
                "expected_species": expected_species,
                "predicted_species": predicted_species,
                "species_ok": species_ok,
                "router": route.get("router", "rules"),
                "router_error": route.get("router_error", ""),
            }
        )

    total = len(HERMES_ROUTER_TEST_CASES)
    return {
        "ok": True,
        "model": HERMES_CHAT_MODEL if use_ollama and HERMES_CHAT_ENABLED else "rules",
        "chat_provider": HERMES_CHAT_PROVIDER,
        "chat_enabled": HERMES_CHAT_ENABLED,
        "total": total,
        "tool_accuracy": correct_tool / total if total else 0,
        "species_accuracy": correct_species / total if total else 0,
        "all_accuracy": sum(1 for item in cases if item["tool_ok"] and item["species_ok"]) / total if total else 0,
        "cases": cases,
    }


@router.post("/api/hermes/protein")
async def hermes_protein(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    try:
        return _hermes_protein_service(payload)
    except ValueError as exc:
        return {"ok": False, "tool": "protein_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "protein_search", "message": f"Protein search failed: {exc}", "records": []}


@router.post("/api/hermes/ptm")
async def hermes_ptm(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    try:
        return _hermes_ptm_service(payload)
    except ValueError as exc:
        return {"ok": False, "tool": "ptm_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "ptm_search", "message": f"PTM search failed: {exc}", "records": []}


@router.post("/api/hermes/blast")
async def hermes_blast(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_hermes_assistant_enabled()
    try:
        return _hermes_blast_service(payload)
    except ValueError as exc:
        return {"ok": False, "tool": "blast_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "blast_search", "message": f"BLAST search failed: {exc}", "records": []}

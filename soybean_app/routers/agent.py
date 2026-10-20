import json
import math
import threading
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse

from soybean_app.services import *
from soybean_app.services.agent import *
from soybean_app.research_agent.graph import (
    resume_research_agent,
    run_research_agent,
    stream_research_agent,
)
from soybean_app.research_agent.configuration import get_user_agent_settings
from .common import *

router = APIRouter()


@router.get("/api/agent/schema")
async def agent_schema(request: Request) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    current_user = get_current_user(request)
    runtime_settings = get_user_agent_settings(
        int(current_user.get("user_id", 0) or 0) if current_user else 0
    )
    return {
        "ok": True,
        "name": "Soybean PTM Viewer Agent Tools",
        "version": "1.0",
        "assistant_enabled": AGENT_RUNTIME_ENABLED,
        "chat_provider": runtime_settings.llm_provider,
        "chat_model": runtime_settings.llm_model,
        "workflow": {
            "stream_endpoint": "/api/agent/stream",
            "query_endpoint": "/api/agent/query",
            "resume_endpoint": "/api/agent/resume",
            "checkpoint_backend": "postgresql",
            "supports_interrupt_resume": True,
            "supports_sse": True,
        },
        "agent": {
            "file": str(AGENT_PROMPT_FILE.relative_to(BASE_DIR)) if AGENT_PROMPT_FILE.exists() else "",
            "skills": [str(path.relative_to(BASE_DIR)) for path in _agent_skill_paths()],
        },
        "species_options": SPECIES_OPTIONS,
        "default_species": DEFAULT_SPECIES,
        "tools": [
            {
                "name": "protein_search",
                "endpoint": "/api/agent/protein",
                "description": "Search one or more protein identifiers and return PTM overview, site evidence, and comparison-ready records when authorized.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "species": {"type": "string", "enum": [item["value"] for item in SPECIES_OPTIONS]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": AGENT_TOOL_RESULT_LIMIT_MAX},
                        "site_limit": {"type": "integer", "minimum": 1, "maximum": AGENT_TOOL_RESULT_LIMIT_MAX},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "ptm_search",
                "endpoint": "/api/agent/ptm",
                "description": "Search PTM motif/expression patterns using the same parser as the PTM Search page.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string"},
                        "species": {"type": "string", "enum": [item["value"] for item in SPECIES_OPTIONS]},
                        "sequence_length": {"type": "integer", "minimum": 3, "maximum": 30},
                        "representative_only": {"type": "boolean"},
                        "peptides_unique": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": AGENT_TOOL_RESULT_LIMIT_MAX},
                    },
                    "required": ["expression"],
                },
            },
            {
                "name": "blast_search",
                "endpoint": "/api/agent/blast",
                "description": "Run protein BLAST against cached soybean/rhizobium protein sequences.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sequence": {"type": "string", "maxLength": AGENT_BLAST_SEQUENCE_MAX},
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


@router.post("/api/agent/query")
async def agent_query(request: Request, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    try:
        current_user = get_current_user(request)
        return await run_research_agent(
            payload,
            user_id=int(current_user.get("user_id", 0) or 0) if current_user else 0,
            allow_multiple_identifiers=current_user_can_search_multiple_identifiers(request),
        )
    except ValueError as exc:
        return {"ok": False, "tool": "none", "message": str(exc), "answer": str(exc), "records": []}
    except Exception as exc:
        message = f"Agent query failed: {exc}"
        return {"ok": False, "tool": "none", "message": message, "answer": message, "records": []}


@router.post("/api/agent/resume")
async def agent_resume(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    try:
        if "resume" not in payload:
            raise ValueError("resume is required.")
        current_user = get_current_user(request)
        return await resume_research_agent(
            payload.get("thread_id"),
            payload.get("resume"),
            user_id=int(current_user.get("user_id", 0) or 0) if current_user else 0,
        )
    except ValueError as exc:
        return {"ok": False, "tool": "none", "message": str(exc), "answer": str(exc), "records": []}
    except Exception as exc:
        message = f"Agent resume failed: {exc}"
        return {"ok": False, "tool": "none", "message": message, "answer": message, "records": []}


@router.post("/api/agent/stream")
async def agent_stream(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> StreamingResponse:
    _require_agent_runtime_enabled()

    async def event_source():
        try:
            current_user = get_current_user(request)
            async for event in stream_research_agent(
                payload,
                user_id=int(current_user.get("user_id", 0) or 0) if current_user else 0,
                allow_multiple_identifiers=current_user_can_search_multiple_identifiers(request),
            ):
                if event.get("event") == "heartbeat":
                    yield ": keep-alive\n\n"
                    continue
                event_name = str(event.get("event") or "message")
                event_data = json.dumps(event.get("data") or {}, ensure_ascii=False, default=str)
                yield f"event: {event_name}\ndata: {event_data}\n\n"
        except Exception as exc:
            event_data = json.dumps(
                {
                    "ok": False,
                    "message": str(exc),
                    "answer": f"Agent request failed: {exc}",
                },
                ensure_ascii=False,
            )
            yield f"event: error\ndata: {event_data}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/agent/protein")
async def agent_protein(
    request: Request,
    payload: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    try:
        authorized_payload = {
            **payload,
            "_allow_multiple_identifiers": current_user_can_search_multiple_identifiers(request),
        }
        return _agent_protein_service(authorized_payload)
    except ValueError as exc:
        return {"ok": False, "tool": "protein_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "protein_search", "message": f"Protein search failed: {exc}", "records": []}


@router.post("/api/agent/ptm")
async def agent_ptm(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    try:
        return _agent_ptm_service(payload)
    except ValueError as exc:
        return {"ok": False, "tool": "ptm_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "ptm_search", "message": f"PTM search failed: {exc}", "records": []}


@router.post("/api/agent/blast")
async def agent_blast(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    _require_agent_runtime_enabled()
    try:
        return _agent_blast_service(payload)
    except ValueError as exc:
        return {"ok": False, "tool": "blast_search", "message": str(exc), "records": []}
    except Exception as exc:
        return {"ok": False, "tool": "blast_search", "message": f"BLAST search failed: {exc}", "records": []}

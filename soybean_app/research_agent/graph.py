from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from soybean_app.services import split_identifier_query
from soybean_app.research_agent.configuration import get_user_agent_settings
from soybean_app.research_agent.model import create_chat_model
from soybean_app.research_agent.settings import get_agent_settings
from soybean_app.research_agent.state import ResearchState
from soybean_app.research_agent.tools import AGENT_TOOLS, AGENT_TOOLS_BY_NAME


AGENT_ROOT = Path(__file__).resolve().parent
SYSTEM_PROMPT_FILE = AGENT_ROOT / "prompts" / "system.md"
SKILL_DIR = AGENT_ROOT / "skills"

research_graph = None
_checkpoint_pool: ConnectionPool | None = None
_runtime_lock = threading.Lock()


@lru_cache(maxsize=1)
def load_agent_instructions() -> str:
    prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    skill_sections: list[str] = []
    for path in sorted(SKILL_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if content:
            skill_sections.append(f"## Skill: {path.stem}\n\n{content}")

    return "\n\n".join([prompt, *skill_sections])


def create_tool_calling_model(user_id: int = 0):
    settings = get_user_agent_settings(user_id)
    return create_chat_model(settings).bind_tools(AGENT_TOOLS, tool_choice="auto")


def call_agent_model(state: ResearchState) -> dict[str, Any]:
    """Let the model answer directly or emit a structured tool call."""

    response = create_tool_calling_model(int(state.get("user_id", 0) or 0)).invoke(
        [
            SystemMessage(content=load_agent_instructions()),
            *state.get("messages", []),
        ]
    )
    return {
        "messages": [response],
        "steps": ["call_agent_model"],
    }


def _explicit_identifiers(text: str) -> list[str]:
    patterns = [
        r"(?<![A-Za-z0-9])GLYMA[._-]?\d+G\d+(?:[._-]?P)?(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])\d+G\d+(?:[._-]?P)?(?![A-Za-z0-9])",
        r"(?<![A-Za-z0-9])[A-Z][0-9][A-Z0-9]{4,9}(?![A-Za-z0-9])",
    ]
    identifiers: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = match.group(0)
            key = value.lower()
            if key not in seen:
                seen.add(key)
                identifiers.append(value)
    return identifiers


def guard_user_request(state: ResearchState) -> dict[str, Any]:
    """Pause restricted multi-ID requests before the model or database runs."""

    identifiers = _explicit_identifiers(state.get("user_query", ""))
    if len(identifiers) <= 1 or state.get("allow_multiple_identifiers", False):
        return {"steps": ["guard_user_request"]}

    resume_value = interrupt(
        {
            "type": "identifier_selection",
            "message": "This account can search one identifier at a time. Choose one identifier to continue.",
            "options": identifiers,
        }
    )
    if isinstance(resume_value, dict):
        selected_identifier = str(
            resume_value.get("identifier")
            or resume_value.get("value")
            or ""
        ).strip()
    else:
        selected_identifier = str(resume_value or "").strip()
    if selected_identifier not in identifiers:
        raise ValueError(
            "The selected identifier must be one of: " + ", ".join(identifiers)
        )

    replacement_query = f"Search protein {selected_identifier} and summarize its PTM sites."
    return {
        "user_query": replacement_query,
        "messages": [
            HumanMessage(
                content=replacement_query,
                id=state.get("current_message_id"),
            )
        ],
        "steps": ["guard_user_request"],
    }


def route_after_model(state: ResearchState) -> Literal["execute_tools", "finish"]:
    """Choose an edge from the model's actual tool-call output."""

    messages = state.get("messages", [])
    if not messages:
        return "finish"

    tool_calls = getattr(messages[-1], "tool_calls", None) or []
    max_tool_calls = get_agent_settings().max_tool_calls
    if tool_calls and state.get("tool_call_count", 0) < max_tool_calls:
        return "execute_tools"

    return "finish"


def execute_tools(state: ResearchState) -> dict[str, Any]:
    """Execute model-selected tools against the real application services."""

    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    tool_calls = getattr(last_message, "tool_calls", None) or []
    max_tool_calls = get_agent_settings().max_tool_calls
    remaining = max(max_tool_calls - state.get("tool_call_count", 0), 0)

    tool_results: list[dict[str, Any]] = []
    executed_calls: list[dict[str, Any]] = []
    pending_calls = [dict(tool_call) for tool_call in tool_calls[:remaining]]

    if not state.get("allow_multiple_identifiers", False):
        identifiers: list[str] = []
        for tool_call in pending_calls:
            if str(tool_call.get("name") or "") != "protein_search":
                continue
            arguments = tool_call.get("args")
            if isinstance(arguments, dict):
                identifiers.extend(
                    split_identifier_query(str(arguments.get("query") or ""))
                )
        identifiers = list(dict.fromkeys(identifiers))
        if len(identifiers) > 1:
            resume_value = interrupt(
                {
                    "type": "identifier_selection",
                    "message": "This account can search one identifier at a time. Choose one identifier to continue.",
                    "options": identifiers,
                }
            )
            if isinstance(resume_value, dict):
                selected_identifier = str(
                    resume_value.get("identifier")
                    or resume_value.get("value")
                    or ""
                ).strip()
            else:
                selected_identifier = str(resume_value or "").strip()
            if selected_identifier not in identifiers:
                raise ValueError(
                    "The selected identifier must be one of: "
                    + ", ".join(identifiers)
                )
            selected_call = next(
                tool_call
                for tool_call in pending_calls
                if str(tool_call.get("name") or "") == "protein_search"
            )
            selected_call["args"] = {
                **(selected_call.get("args") or {}),
                "query": selected_identifier,
            }
            pending_calls = [selected_call]

    for tool_call in pending_calls:
        tool_name = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or tool_name or "tool-call")
        arguments = tool_call.get("args")
        if not isinstance(arguments, dict):
            arguments = {}

        selected_tool = AGENT_TOOLS_BY_NAME.get(tool_name)
        if selected_tool is None:
            result: dict[str, Any] = {
                "ok": False,
                "tool": tool_name or "unknown",
                "message": f"Unknown agent tool: {tool_name or '<empty>'}",
                "records": [],
            }
        else:
            invoke_arguments = dict(arguments)
            if tool_name == "protein_search":
                invoke_arguments["allow_multiple_identifiers"] = bool(
                    state.get("allow_multiple_identifiers", False)
                )
            try:
                raw_result = selected_tool.invoke(invoke_arguments)
                result = raw_result if isinstance(raw_result, dict) else {
                    "ok": True,
                    "tool": tool_name,
                    "message": str(raw_result),
                    "records": [],
                }
            except ValueError as exc:
                result = {
                    "ok": False,
                    "tool": tool_name,
                    "message": str(exc),
                    "records": [],
                }
            except Exception as exc:
                result = {
                    "ok": False,
                    "tool": tool_name,
                    "message": f"{tool_name} failed: {exc}",
                    "records": [],
                }

        result.setdefault("tool", tool_name)
        result["router"] = "langgraph"
        tool_results.append(result)
        executed_calls.append(
            {
                "name": tool_name,
                "id": tool_call_id,
            }
        )

    return {
        "pending_tool_calls": executed_calls,
        "tool_results": tool_results,
        "tool_call_count": state.get("tool_call_count", 0) + len(tool_results),
        "steps": ["execute_tools"],
    }


def validate_evidence(state: ResearchState) -> dict[str, Any]:
    """Validate tool evidence before it is exposed to the answer model."""

    validated_results: list[dict[str, Any]] = []
    tool_messages: list[ToolMessage] = []
    checks: list[dict[str, Any]] = []
    pending_calls = state.get("pending_tool_calls", [])

    for index, raw_result in enumerate(state.get("tool_results", [])):
        result = dict(raw_result)
        records = result.get("records")
        records_valid = isinstance(records, list) and all(
            isinstance(record, dict) for record in (records or [])
        )
        if not records_valid:
            records = []
            result["records"] = records

        summary = result.get("summary")
        count_consistent = True
        if isinstance(summary, dict) and "returned_records" in summary:
            try:
                count_consistent = int(summary["returned_records"]) == len(records)
            except (TypeError, ValueError):
                count_consistent = False

        evidence = []
        for record in records:
            identity = str(
                record.get("display_id")
                or record.get("protein_accession")
                or record.get("gene_name")
                or record.get("hit_label")
                or ""
            ).strip()
            if identity:
                evidence.append(
                    {
                        "identifier": identity,
                        "detail_url": str(record.get("detail_url") or ""),
                    }
                )

        passed = records_valid and count_consistent
        if not passed:
            result["ok"] = False
            result["message"] = "Tool output failed evidence validation."
        validation = {
            "passed": passed,
            "records_valid": records_valid,
            "count_consistent": count_consistent,
            "evidence_count": len(evidence),
        }
        result["evidence"] = evidence
        result["validation"] = validation
        validated_results.append(result)
        checks.append(validation)

        call = pending_calls[index] if index < len(pending_calls) else {}
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False, default=str),
                tool_call_id=str(call.get("id") or f"tool-call-{index}"),
                name=str(call.get("name") or result.get("tool") or "agent_tool"),
            )
        )

    overall_passed = bool(checks) and all(check["passed"] for check in checks)
    return {
        "messages": tool_messages,
        "tool_results": validated_results,
        "evidence_validation": {
            "passed": overall_passed,
            "tool_result_count": len(validated_results),
            "evidence_count": sum(check["evidence_count"] for check in checks),
            "checks": checks,
        },
        "steps": ["validate_evidence"],
    }


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content or "").strip()


def finish_response(state: ResearchState) -> dict[str, Any]:
    """Convert graph state into the stable response consumed by the website UI."""

    answer = ""
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage):
            answer = _message_text(message)
            if answer:
                break

    tool_results = state.get("tool_results", [])
    if tool_results:
        final_result = dict(tool_results[-1])
        final_result["answer"] = answer or str(
            final_result.get("message") or "The query completed."
        )
        final_result["routed_tool"] = final_result.get("tool")
        final_result["router"] = "langgraph"
        evidence_validation = state.get("evidence_validation") or {}
        final_result["evaluation"] = {
            **evidence_validation,
            "answer_present": bool(answer),
            "status": (
                "passed"
                if evidence_validation.get("passed") and answer
                else "warning"
            ),
        }
    else:
        final_result = {
            "ok": True,
            "tool": "none",
            "routed_tool": "none",
            "router": "langgraph",
            "message": answer,
            "answer": answer or "Please provide a protein, PTM pattern, or amino-acid sequence.",
            "records": [],
        }

    return {
        "answer": final_result["answer"],
        "final_result": final_result,
        "steps": ["finish_response"],
    }


def create_research_graph(checkpointer=None):
    builder = StateGraph(ResearchState)
    builder.add_node("guard_user_request", guard_user_request)
    builder.add_node("agent_model", call_agent_model)
    builder.add_node("execute_tools", execute_tools)
    builder.add_node("validate_evidence", validate_evidence)
    builder.add_node("finish_response", finish_response)
    builder.add_edge(START, "guard_user_request")
    builder.add_edge("guard_user_request", "agent_model")
    builder.add_conditional_edges(
        "agent_model",
        route_after_model,
        {
            "execute_tools": "execute_tools",
            "finish": "finish_response",
        },
    )
    builder.add_edge("execute_tools", "validate_evidence")
    builder.add_edge("validate_evidence", "agent_model")
    builder.add_edge("finish_response", END)
    return builder.compile(checkpointer=checkpointer)


def initialize_agent_runtime() -> None:
    """Open PostgreSQL checkpoint storage and compile the persistent graph."""

    global research_graph, _checkpoint_pool
    if research_graph is not None:
        return

    with _runtime_lock:
        if research_graph is not None:
            return

        settings = get_agent_settings()
        if not settings.runtime_enabled:
            return
        if not settings.checkpoint_dsn:
            raise RuntimeError("AGENT_CHECKPOINT_DSN or PTM_DB_* configuration is required.")

        checkpoint_pool = ConnectionPool(
            conninfo=settings.checkpoint_dsn,
            min_size=1,
            max_size=4,
            open=True,
            check=ConnectionPool.check_connection,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        try:
            checkpoint_pool.wait(timeout=10)
            checkpointer = PostgresSaver(checkpoint_pool)
            checkpointer.setup()
            research_graph = create_research_graph(checkpointer=checkpointer)
            _checkpoint_pool = checkpoint_pool
        except Exception:
            checkpoint_pool.close()
            raise


def close_agent_runtime() -> None:
    """Close the checkpoint connection owned by the application lifespan."""

    global research_graph, _checkpoint_pool
    checkpoint_pool = _checkpoint_pool
    research_graph = None
    _checkpoint_pool = None
    if checkpoint_pool is not None:
        checkpoint_pool.close()


def normalize_thread_id(value: Any) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return str(uuid4())
    try:
        return str(UUID(raw_value))
    except ValueError as exc:
        raise ValueError("thread_id must be a valid UUID.") from exc


def _interrupt_result(state: dict[str, Any], thread_id: str) -> dict[str, Any] | None:
    interrupts = state.get("__interrupt__") or []
    if not interrupts:
        return None
    first_interrupt = interrupts[0]
    interrupt_value = getattr(first_interrupt, "value", first_interrupt)
    if not isinstance(interrupt_value, dict):
        interrupt_value = {
            "type": "input_required",
            "message": str(interrupt_value),
        }
    return {
        "ok": True,
        "status": "interrupted",
        "requires_input": True,
        "tool": "none",
        "routed_tool": "none",
        "router": "langgraph",
        "message": str(interrupt_value.get("message") or "Additional input is required."),
        "answer": str(interrupt_value.get("message") or "Additional input is required."),
        "interrupt": interrupt_value,
        "records": [],
        "thread_id": thread_id,
    }


def _completed_result(state: dict[str, Any], thread_id: str) -> dict[str, Any]:
    interrupted = _interrupt_result(state, thread_id)
    if interrupted is not None:
        return interrupted
    final_result = state.get("final_result")
    if not isinstance(final_result, dict):
        raise RuntimeError("Agent workflow completed without a response.")
    final_result["thread_id"] = thread_id
    final_result["requires_input"] = False
    return final_result


def _run_research_agent(
    payload: dict[str, Any],
    *,
    user_id: int = 0,
    allow_multiple_identifiers: bool = False,
) -> dict[str, Any]:
    user_query = str(
        payload.get("message")
        or payload.get("query")
        or payload.get("text")
        or payload.get("identifier")
        or payload.get("gene_name")
        or payload.get("expression")
        or payload.get("sequence")
        or ""
    ).strip()
    if not user_query:
        raise ValueError("Please enter a question or search value.")

    thread_id = normalize_thread_id(payload.get("thread_id"))
    initialize_agent_runtime()
    if research_graph is None:
        raise RuntimeError("Agent Runtime is not initialized.")

    settings = get_agent_settings()
    current_message_id = str(uuid4())
    state = research_graph.invoke(
        {
            "user_query": user_query,
            "current_message_id": current_message_id,
            "request_payload": dict(payload),
            "user_id": int(user_id or 0),
            "allow_multiple_identifiers": allow_multiple_identifiers,
            "messages": [HumanMessage(content=user_query, id=current_message_id)],
            "steps": [],
            "tool_call_count": 0,
            "pending_tool_calls": [],
            "tool_results": [],
        },
        config={
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(10, settings.max_tool_calls * 3 + 5),
        },
    )
    return _completed_result(state, thread_id)


async def run_research_agent(
    payload: dict[str, Any],
    *,
    user_id: int = 0,
    allow_multiple_identifiers: bool = False,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _run_research_agent,
        payload,
        user_id=user_id,
        allow_multiple_identifiers=allow_multiple_identifiers,
    )


def _resume_research_agent(
    thread_id: Any,
    resume_value: Any,
    *,
    user_id: int = 0,
) -> dict[str, Any]:
    normalized_thread_id = normalize_thread_id(thread_id)
    initialize_agent_runtime()
    if research_graph is None:
        raise RuntimeError("Agent Runtime is not initialized.")

    settings = get_agent_settings()
    config = {
        "configurable": {"thread_id": normalized_thread_id},
        "recursion_limit": max(10, settings.max_tool_calls * 3 + 5),
    }
    snapshot = research_graph.get_state(config)
    owner_user_id = int((snapshot.values or {}).get("user_id", 0) or 0)
    if owner_user_id != int(user_id or 0):
        raise ValueError("This Agent conversation belongs to a different account.")
    state = research_graph.invoke(Command(resume=resume_value), config=config)
    return _completed_result(state, normalized_thread_id)


async def resume_research_agent(
    thread_id: Any,
    resume_value: Any,
    *,
    user_id: int = 0,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _resume_research_agent,
        thread_id,
        resume_value,
        user_id=user_id,
    )


_PROGRESS_LABELS = {
    "guard_user_request": "Validating request",
    "agent_model": "Analyzing request",
    "execute_tools": "Querying database",
    "validate_evidence": "Validating evidence",
    "finish_response": "Preparing answer",
}

_TRANSIENT_DATABASE_ERROR_MARKERS = (
    "connection is closed",
    "connection reset",
    "connection abort",
    "consuming input failed",
    "could not receive data from server",
    "server closed the connection unexpectedly",
    "terminating connection",
)


def _is_transient_database_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    return any(marker in message for marker in _TRANSIENT_DATABASE_ERROR_MARKERS)


async def stream_research_agent(
    payload: dict[str, Any],
    *,
    user_id: int = 0,
    allow_multiple_identifiers: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Stream production graph progress and the final stable API result."""

    is_resume = "resume" in payload
    if is_resume and not str(payload.get("thread_id") or "").strip():
        raise ValueError("thread_id is required when resuming an agent run.")

    thread_id = normalize_thread_id(payload.get("thread_id"))
    settings = get_agent_settings()
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": max(10, settings.max_tool_calls * 3 + 5),
    }

    if is_resume:
        graph_input: Any = Command(resume=payload.get("resume"))
    else:
        user_query = str(
            payload.get("message")
            or payload.get("query")
            or payload.get("text")
            or payload.get("identifier")
            or payload.get("gene_name")
            or payload.get("expression")
            or payload.get("sequence")
            or ""
        ).strip()
        if not user_query:
            raise ValueError("Please enter a question or search value.")
        current_message_id = str(uuid4())
        graph_input = {
            "user_query": user_query,
            "current_message_id": current_message_id,
            "request_payload": dict(payload),
            "user_id": int(user_id or 0),
            "allow_multiple_identifiers": allow_multiple_identifiers,
            "messages": [HumanMessage(content=user_query, id=current_message_id)],
            "steps": [],
            "tool_call_count": 0,
            "pending_tool_calls": [],
            "tool_results": [],
        }

    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    event_loop = asyncio.get_running_loop()

    def emit(event: dict[str, Any] | None) -> None:
        event_loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def run_graph_stream() -> None:
        try:
            initialize_agent_runtime()
            if research_graph is None:
                raise RuntimeError("Agent Runtime is not initialized.")

            if is_resume:
                snapshot = research_graph.get_state(config)
                owner_user_id = int((snapshot.values or {}).get("user_id", 0) or 0)
                if owner_user_id != int(user_id or 0):
                    raise ValueError("This Agent conversation belongs to a different account.")

            max_attempts = 1 if is_resume else 2
            for attempt in range(max_attempts):
                try:
                    for update in research_graph.stream(
                        graph_input,
                        config=config,
                        stream_mode="updates",
                    ):
                        if not isinstance(update, dict):
                            continue
                        for node_name in update:
                            label = _PROGRESS_LABELS.get(node_name)
                            if label:
                                emit(
                                    {
                                        "event": "progress",
                                        "data": {
                                            "node": node_name,
                                            "message": label,
                                            "thread_id": thread_id,
                                        },
                                    }
                                )

                    snapshot = research_graph.get_state(config)
                    state = dict(snapshot.values)
                    pending_interrupts = [
                        pending_interrupt
                        for task in snapshot.tasks
                        for pending_interrupt in (getattr(task, "interrupts", ()) or ())
                    ]
                    if pending_interrupts:
                        state["__interrupt__"] = tuple(pending_interrupts)
                    emit(
                        {
                            "event": "result",
                            "data": _completed_result(state, thread_id),
                        }
                    )
                    break
                except Exception as exc:
                    can_retry = (
                        attempt + 1 < max_attempts
                        and _is_transient_database_error(exc)
                    )
                    if not can_retry:
                        raise
                    emit(
                        {
                            "event": "progress",
                            "data": {
                                "node": "reconnect_database",
                                "message": "Reconnecting database",
                                "thread_id": thread_id,
                            },
                        }
                    )
                    time.sleep(0.25)
        except Exception as exc:
            emit(
                {
                    "event": "error",
                    "data": {
                        "ok": False,
                        "message": str(exc),
                        "answer": f"Agent request failed: {exc}",
                        "thread_id": thread_id,
                    },
                }
            )
        finally:
            emit(None)

    worker = asyncio.create_task(asyncio.to_thread(run_graph_stream))
    yield {
        "event": "start",
        "data": {"message": "Starting agent workflow", "thread_id": thread_id},
    }

    while True:
        try:
            event = await asyncio.wait_for(event_queue.get(), timeout=15)
        except asyncio.TimeoutError:
            yield {"event": "heartbeat", "data": {"thread_id": thread_id}}
            continue
        if event is None:
            break
        yield event

    await worker


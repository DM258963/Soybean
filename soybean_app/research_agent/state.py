from operator import add
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ResearchState(TypedDict, total=False):
    """Shared state for the production PTM research workflow."""

    user_query: str
    current_message_id: str
    request_payload: dict[str, Any]
    user_id: int
    allow_multiple_identifiers: bool
    messages: Annotated[list[AnyMessage], add_messages]
    steps: Annotated[list[str], add]
    tool_call_count: int
    pending_tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    evidence_validation: dict[str, Any]
    answer: str
    final_result: dict[str, Any]

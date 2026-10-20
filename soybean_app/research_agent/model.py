from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from soybean_app.research_agent.settings import AgentSettings, get_agent_settings


def create_chat_model(settings: AgentSettings | None = None) -> BaseChatModel:
    """Create the chat model used by PTM intelligence workflows."""

    settings = settings or get_agent_settings()

    if not settings.runtime_enabled:
        raise RuntimeError("Agent Runtime is disabled.")
    if not settings.llm_enabled:
        raise RuntimeError("Agent LLM integration is disabled.")

    supported_providers = {
        "groq",
        "openai",
        "openai_compatible",
    }

    if settings.llm_provider not in supported_providers:
        raise RuntimeError(
            "Unsupported Agent LLM provider: "
            f"{settings.llm_provider or '<empty>'}"
        )

    if not settings.llm_base_url:
        raise RuntimeError("AGENT_LLM_BASE_URL is required.")

    if not settings.llm_model:
        raise RuntimeError("AGENT_LLM_MODEL is required.")

    if settings.llm_mode != "local" and not settings.llm_api_key:
        raise RuntimeError("AGENT_LLM_API_KEY is required.")

    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "local-model",
        temperature=0,
        timeout=settings.llm_timeout,
        max_retries=settings.max_retries,
    )

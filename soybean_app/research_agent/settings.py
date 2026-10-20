from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass
from functools import lru_cache

from soybean_app.core.env import load_project_env


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_value(
    name: str,
    *,
    default: str = "",
) -> str:
    """Read a canonical Agent Runtime environment setting."""

    value = os.getenv(name)
    if value is not None:
        return value.strip()

    return default


def _env_bool(
    name: str,
    *,
    default: bool = False,
) -> bool:
    raw_value = _env_value(
        name,
        default="true" if default else "false",
    ).lower()

    if raw_value in _TRUE_VALUES:
        return True
    if raw_value in _FALSE_VALUES:
        return False

    raise RuntimeError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0."
    )


def _env_positive_int(
    name: str,
    *,
    default: int,
) -> int:
    raw_value = _env_value(name, default=str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc

    if value < 1:
        raise RuntimeError(f"{name} must be greater than zero.")

    return value


def _env_positive_float(
    name: str,
    *,
    default: float,
) -> float:
    raw_value = _env_value(name, default=str(default))

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric.") from exc

    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")

    return value


@dataclass(frozen=True, slots=True)
class AgentSettings:
    runtime_enabled: bool
    llm_enabled: bool
    llm_mode: str
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: float
    router_timeout: float
    summary_timeout: float
    checkpoint_dsn: str
    max_tool_calls: int
    max_retries: int
    tool_result_limit_default: int
    tool_result_limit_max: int
    blast_sequence_max: int
    definition_dir: str


def _default_checkpoint_dsn() -> str:
    user = urllib.parse.quote(os.getenv("PTM_DB_USER", "myuser"), safe="")
    password = urllib.parse.quote(os.getenv("PTM_DB_PASSWORD", "wowangle"), safe="")
    host = os.getenv("PTM_DB_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("PTM_DB_PORT", "5432").strip() or "5432"
    database = urllib.parse.quote(os.getenv("PTM_DB_NAME", "ptm_prod"), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    """Load and validate Agent Runtime settings once per process."""

    load_project_env()

    base_url = _env_value("AGENT_LLM_BASE_URL").rstrip("/")
    inferred_mode = (
        "local"
        if any(marker in base_url.lower() for marker in ("127.0.0.1", "localhost", "host.docker.internal"))
        else "api"
    )
    values: dict[str, object] = {
        "runtime_enabled": _env_bool(
            "AGENT_RUNTIME_ENABLED",
            default=False,
        ),
        "llm_enabled": _env_bool(
            "AGENT_LLM_ENABLED",
            default=True,
        ),
        "llm_mode": _env_value(
            "AGENT_LLM_MODE",
            default=inferred_mode,
        ).lower(),
        "llm_provider": _env_value(
            "AGENT_LLM_PROVIDER",
            default="groq",
        ).lower(),
        "llm_base_url": base_url,
        "llm_model": _env_value(
            "AGENT_LLM_MODEL",
        ),
        "llm_api_key": _env_value(
            "AGENT_LLM_API_KEY",
        ),
        "llm_timeout": _env_positive_float(
            "AGENT_LLM_TIMEOUT",
            default=30,
        ),
        "router_timeout": _env_positive_float(
            "AGENT_ROUTER_TIMEOUT",
            default=8,
        ),
        "summary_timeout": _env_positive_float(
            "AGENT_SUMMARY_TIMEOUT",
            default=12,
        ),
        "checkpoint_dsn": (
            _env_value("AGENT_CHECKPOINT_DSN")
            or _default_checkpoint_dsn()
        ),
        "max_tool_calls": _env_positive_int(
            "AGENT_MAX_TOOL_CALLS",
            default=10,
        ),
        "max_retries": _env_positive_int(
            "AGENT_MAX_RETRIES",
            default=2,
        ),
        "tool_result_limit_default": _env_positive_int(
            "AGENT_TOOL_RESULT_LIMIT_DEFAULT",
            default=10,
        ),
        "tool_result_limit_max": _env_positive_int(
            "AGENT_TOOL_RESULT_LIMIT_MAX",
            default=50,
        ),
        "blast_sequence_max": _env_positive_int(
            "AGENT_BLAST_SEQUENCE_MAX",
            default=5000,
        ),
        "definition_dir": _env_value(
            "AGENT_DEFINITION_DIR",
            default="research_agent",
        ),
    }
    return AgentSettings(**values)

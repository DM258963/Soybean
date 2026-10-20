from __future__ import annotations

import os
import re
import socket
import threading
import urllib.parse
from dataclasses import replace
from ipaddress import ip_address
from typing import Any

from soybean_app.core.env import load_project_env
from soybean_app.core.foundation import get_db_pool
from soybean_app.research_agent.settings import AgentSettings, get_agent_settings


_CONFIG_TABLE_LOCK = threading.Lock()
_CONFIG_TABLE_READY = False
_MODES = {"local", "api"}
_PROVIDERS = {"openai", "groq", "openai_compatible"}
_OFFICIAL_API_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
}


def _encryption_secret() -> str:
    load_project_env()
    secret = (
        os.getenv("AGENT_SETTINGS_SECRET_KEY", "").strip()
        or os.getenv("PTM_AUTH_SECRET_KEY", "").strip()
    )
    if len(secret) < 32 or secret == "replace-with-a-long-random-secret":
        raise RuntimeError(
            "AGENT_SETTINGS_SECRET_KEY (or PTM_AUTH_SECRET_KEY) must be a unique secret of at least 32 characters."
        )
    return secret


def ensure_user_agent_configuration_table() -> None:
    global _CONFIG_TABLE_READY
    if _CONFIG_TABLE_READY:
        return
    with _CONFIG_TABLE_LOCK:
        if _CONFIG_TABLE_READY:
            return
        with get_db_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ptm.user_agent_model_profile (
                      user_id BIGINT NOT NULL
                        REFERENCES ptm.app_user(user_id) ON DELETE CASCADE,
                      mode TEXT NOT NULL CHECK (mode IN ('local', 'api')),
                      provider TEXT NOT NULL
                        CHECK (provider IN ('openai', 'groq', 'openai_compatible')),
                      base_url TEXT NOT NULL,
                      model_name TEXT NOT NULL,
                      api_key_cipher BYTEA,
                      llm_timeout DOUBLE PRECISION NOT NULL DEFAULT 30
                        CHECK (llm_timeout >= 1 AND llm_timeout <= 300),
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      PRIMARY KEY (user_id, mode)
                    );

                    CREATE TABLE IF NOT EXISTS ptm.user_agent_runtime_preference (
                      user_id BIGINT PRIMARY KEY
                        REFERENCES ptm.app_user(user_id) ON DELETE CASCADE,
                      active_mode TEXT NOT NULL CHECK (active_mode IN ('local', 'api')),
                      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                cur.execute("SELECT to_regclass('ptm.user_agent_model_config');")
                if cur.fetchone()[0] is not None:
                    cur.execute(
                        """
                        INSERT INTO ptm.user_agent_model_profile (
                          user_id, mode, provider, base_url, model_name,
                          api_key_cipher, llm_timeout, created_at, updated_at
                        )
                        SELECT user_id, mode, provider, base_url, model_name,
                               api_key_cipher, llm_timeout, created_at, updated_at
                        FROM ptm.user_agent_model_config
                        ON CONFLICT (user_id, mode) DO NOTHING;

                        INSERT INTO ptm.user_agent_runtime_preference (
                          user_id, active_mode, updated_at
                        )
                        SELECT user_id, mode, updated_at
                        FROM ptm.user_agent_model_config
                        ON CONFLICT (user_id) DO NOTHING;
                        """
                    )
        _CONFIG_TABLE_READY = True


def initialize_user_agent_configuration_storage() -> None:
    """Create per-user model storage after the business database pool starts."""

    ensure_user_agent_configuration_table()


def _allowed_local_model_hosts() -> set[str]:
    load_project_env()
    configured = os.getenv(
        "AGENT_LOCAL_MODEL_HOSTS",
        "127.0.0.1,localhost,::1,host.docker.internal,ollama",
    )
    return {
        host.strip().strip("[]").lower()
        for host in configured.split(",")
        if host.strip()
    }


def _require_public_api_host(hostname: str) -> None:
    clean_host = hostname.strip().strip("[]").lower()
    if not clean_host or clean_host == "localhost" or clean_host.endswith((".local", ".internal")):
        raise ValueError("Custom API endpoints must use a public HTTPS host.")
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ValueError("The custom API host could not be resolved.") from exc
    if not addresses:
        raise ValueError("The custom API host could not be resolved.")
    for address in addresses:
        parsed_address = ip_address(address)
        if not parsed_address.is_global:
            raise ValueError("Custom API endpoints cannot resolve to a private or local address.")


def _validate_configuration(values: dict[str, Any]) -> dict[str, Any]:
    mode = str(values.get("mode") or "").strip().lower()
    if mode not in _MODES:
        raise ValueError("Choose either Local model or Model API.")

    provider = str(values.get("provider") or "").strip().lower()
    if mode == "local":
        provider = "openai_compatible"
    if provider not in _PROVIDERS:
        raise ValueError("Choose a supported model provider.")

    base_url = str(values.get("base_url") or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL must be a complete http:// or https:// URL.")
    if parsed.username or parsed.password:
        raise ValueError("Do not include credentials in the Base URL.")
    hostname = str(parsed.hostname or "").strip().lower()
    if mode == "local":
        if hostname.strip("[]") not in _allowed_local_model_hosts():
            raise ValueError(
                "This local model host is not allowed by AGENT_LOCAL_MODEL_HOSTS."
            )
    elif provider in _OFFICIAL_API_URLS:
        base_url = _OFFICIAL_API_URLS[provider]
    else:
        if parsed.scheme != "https":
            raise ValueError("Custom model APIs must use HTTPS.")
        _require_public_api_host(hostname)

    model_name = str(values.get("model_name") or "").strip()
    if not model_name or len(model_name) > 200 or re.search(r"[\r\n\x00]", model_name):
        raise ValueError("Enter a valid model name of at most 200 characters.")

    try:
        llm_timeout = float(values.get("llm_timeout") or 30)
    except (TypeError, ValueError) as exc:
        raise ValueError("Timeout must be numeric.") from exc
    if not 1 <= llm_timeout <= 300:
        raise ValueError("Timeout must be between 1 and 300 seconds.")

    api_key = str(values.get("api_key") or "").strip()
    if len(api_key) > 4096:
        raise ValueError("API key is too long.")

    return {
        "mode": mode,
        "provider": provider,
        "base_url": base_url,
        "model_name": model_name,
        "llm_timeout": llm_timeout,
        "api_key": api_key,
    }


def _load_user_configuration(
    user_id: int,
    mode: str | None = None,
) -> dict[str, Any] | None:
    if int(user_id or 0) <= 0:
        return None
    ensure_user_agent_configuration_table()
    secret = _encryption_secret()
    with get_db_pool().connection() as conn:
        with conn.cursor() as cur:
            if mode in _MODES:
                cur.execute(
                    """
                    SELECT mode, provider, base_url, model_name,
                           CASE
                             WHEN api_key_cipher IS NOT NULL
                             THEN pgp_sym_decrypt(api_key_cipher, %s)::TEXT
                             ELSE NULL
                           END AS api_key,
                           llm_timeout, updated_at
                    FROM ptm.user_agent_model_profile
                    WHERE user_id = %s AND mode = %s;
                    """,
                    (secret, int(user_id), mode),
                )
            else:
                cur.execute(
                    """
                    SELECT profile.mode, profile.provider, profile.base_url,
                           profile.model_name,
                           CASE
                             WHEN profile.api_key_cipher IS NOT NULL
                             THEN pgp_sym_decrypt(profile.api_key_cipher, %s)::TEXT
                             ELSE NULL
                           END AS api_key,
                           profile.llm_timeout, profile.updated_at
                    FROM ptm.user_agent_model_profile AS profile
                    LEFT JOIN ptm.user_agent_runtime_preference AS preference
                      ON preference.user_id = profile.user_id
                    WHERE profile.user_id = %s
                    ORDER BY
                      CASE WHEN profile.mode = preference.active_mode THEN 0 ELSE 1 END,
                      profile.updated_at DESC
                    LIMIT 1;
                    """,
                    (secret, int(user_id)),
                )
            row = cur.fetchone()
    if not row:
        return None
    return {
        "mode": str(row[0]),
        "provider": str(row[1]),
        "base_url": str(row[2]),
        "model_name": str(row[3]),
        "api_key": str(row[4] or ""),
        "llm_timeout": float(row[5]),
        "updated_at": row[6],
    }


def get_user_agent_settings(user_id: int = 0) -> AgentSettings:
    """Return one user's model configuration, falling back to server defaults."""

    defaults = get_agent_settings()
    config = _load_user_configuration(int(user_id or 0))
    if not config:
        return defaults
    return replace(
        defaults,
        llm_mode=config["mode"],
        llm_provider=config["provider"],
        llm_base_url=config["base_url"],
        llm_model=config["model_name"],
        llm_api_key=config["api_key"],
        llm_timeout=config["llm_timeout"],
    )


def get_user_agent_profile_settings(user_id: int, mode: str) -> AgentSettings:
    """Return one mode-specific profile without changing the active profile."""

    if mode not in _MODES:
        raise ValueError("Unsupported Agent model mode.")
    defaults = get_agent_settings()
    config = _load_user_configuration(int(user_id or 0), mode)
    if config:
        return replace(
            defaults,
            llm_mode=config["mode"],
            llm_provider=config["provider"],
            llm_base_url=config["base_url"],
            llm_model=config["model_name"],
            llm_api_key=config["api_key"],
            llm_timeout=config["llm_timeout"],
        )
    if defaults.llm_mode == mode:
        return defaults
    if mode == "local":
        return replace(
            defaults,
            llm_mode="local",
            llm_provider="openai_compatible",
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="",
            llm_api_key="",
        )
    return replace(
        defaults,
        llm_mode="api",
        llm_provider="groq",
        llm_base_url=_OFFICIAL_API_URLS["groq"],
        llm_model="",
        llm_api_key="",
    )


def prepare_user_model_discovery(
    values: dict[str, Any],
    *,
    user_id: int,
) -> dict[str, Any]:
    """Validate a model-list request without persisting the submitted settings."""

    target_user_id = int(user_id or 0)
    if target_user_id <= 0:
        raise ValueError("A signed-in account is required.")

    candidate = dict(values)
    candidate["model_name"] = "model-discovery"
    clean = _validate_configuration(candidate)

    if clean["mode"] == "api" and not clean["api_key"]:
        current = get_user_agent_profile_settings(target_user_id, "api")
        same_connection = (
            current.llm_mode == clean["mode"]
            and current.llm_provider == clean["provider"]
            and current.llm_base_url.rstrip("/") == clean["base_url"]
        )
        if same_connection:
            clean["api_key"] = current.llm_api_key

    if clean["mode"] == "api" and not clean["api_key"]:
        raise ValueError(
            "Enter an API key to retrieve models from this connection."
        )

    return clean


def user_agent_configuration_status(
    user_id: int,
    mode: str | None = None,
) -> dict[str, Any]:
    config = _load_user_configuration(int(user_id), mode)
    if not config:
        return {
            "source": "environment",
            "api_key_configured": False,
            "updated_at": None,
        }
    return {
        "source": "account",
        "api_key_configured": bool(config["api_key"]),
        "updated_at": config["updated_at"],
    }


def save_user_agent_configuration(
    values: dict[str, Any],
    *,
    user_id: int,
) -> dict[str, Any]:
    clean = _validate_configuration(values)
    target_user_id = int(user_id or 0)
    if target_user_id <= 0:
        raise ValueError("A signed-in account is required.")

    ensure_user_agent_configuration_table()
    secret = _encryption_secret()
    existing = _load_user_configuration(target_user_id, clean["mode"])
    if clean["mode"] == "api" and not clean["api_key"] and not (existing and existing["api_key"]):
        raise ValueError("Enter an API key before enabling Model API mode for this account.")

    with get_db_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ptm.user_agent_model_profile (
                  user_id, mode, provider, base_url, model_name, llm_timeout
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, mode) DO UPDATE SET
                  mode = EXCLUDED.mode,
                  provider = EXCLUDED.provider,
                  base_url = EXCLUDED.base_url,
                  model_name = EXCLUDED.model_name,
                  llm_timeout = EXCLUDED.llm_timeout,
                  updated_at = NOW();
                """,
                (
                    target_user_id,
                    clean["mode"],
                    clean["provider"],
                    clean["base_url"],
                    clean["model_name"],
                    clean["llm_timeout"],
                ),
            )
            if clean["api_key"]:
                cur.execute(
                    """
                    UPDATE ptm.user_agent_model_profile
                    SET api_key_cipher = pgp_sym_encrypt(%s, %s, 'cipher-algo=aes256'),
                        updated_at = NOW()
                    WHERE user_id = %s AND mode = 'api';
                    """,
                    (clean["api_key"], secret, target_user_id),
                )
            cur.execute(
                """
                INSERT INTO ptm.user_agent_runtime_preference (
                  user_id, active_mode, updated_at
                ) VALUES (%s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                  active_mode = EXCLUDED.active_mode,
                  updated_at = NOW();
                """,
                (target_user_id, clean["mode"]),
            )

    config = _load_user_configuration(target_user_id, clean["mode"])
    if not config:
        raise RuntimeError("Saved account model configuration could not be reloaded.")
    return config

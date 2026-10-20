import json
import logging
import math
import threading
import time
import urllib.parse
from datetime import date
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
import httpx

from soybean_app.services import *
from soybean_app.services.agent import *
from soybean_app.research_agent.configuration import (
    get_user_agent_settings,
    get_user_agent_profile_settings,
    prepare_user_model_discovery,
    save_user_agent_configuration,
    user_agent_configuration_status,
)
from .common import *

router = APIRouter()
LOGGER = logging.getLogger(__name__)
_LOGIN_RATE_LOCK = threading.Lock()
_LOGIN_FAILURES: dict[str, list[float]] = {}
_GENERIC_LOGIN_ERROR = "Invalid username or password."


def _client_ip(request: Request) -> str:
    return str(request.client.host if request.client else "unknown")[:128]


def _request_user_agent(request: Request) -> str:
    return str(request.headers.get("user-agent", ""))[:512]


def _prune_login_failures(now: float) -> None:
    cutoff = now - (PTM_AUTH_IP_WINDOW_MINUTES * 60)
    stale_keys: list[str] = []
    for key, attempts in _LOGIN_FAILURES.items():
        attempts[:] = [attempt for attempt in attempts if attempt >= cutoff]
        if not attempts:
            stale_keys.append(key)
    for key in stale_keys:
        _LOGIN_FAILURES.pop(key, None)


def _login_rate_keys(request: Request, username: str) -> tuple[str, str]:
    client_ip = _client_ip(request)
    return f"ip:{client_ip}", f"account:{client_ip}:{username}"


def _login_rate_limited(request: Request, username: str) -> bool:
    now = time.monotonic()
    ip_key, account_key = _login_rate_keys(request, username)
    with _LOGIN_RATE_LOCK:
        _prune_login_failures(now)
        return (
            len(_LOGIN_FAILURES.get(account_key, [])) >= PTM_AUTH_IP_MAX_FAILED_ATTEMPTS
            or len(_LOGIN_FAILURES.get(ip_key, [])) >= PTM_AUTH_IP_MAX_FAILED_ATTEMPTS * 5
        )


def _record_login_rate_failure(request: Request, username: str) -> None:
    now = time.monotonic()
    with _LOGIN_RATE_LOCK:
        _prune_login_failures(now)
        for key in _login_rate_keys(request, username):
            _LOGIN_FAILURES.setdefault(key, []).append(now)


def _audit_auth(request: Request, event_type: str, success: bool, **kwargs: Any) -> None:
    try:
        record_auth_audit_event(
            event_type,
            success,
            client_ip=_client_ip(request),
            user_agent=_request_user_agent(request),
            **kwargs,
        )
    except Exception:
        LOGGER.exception("Unable to write authentication audit event: %s", event_type)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    next_url: str = Query(default="/", alias="next"),
) -> Response:
    if get_current_user(request):
        return RedirectResponse(safe_next_url(next_url), status_code=303)
    return render_template(
        request,
        "login.html",
        title="Login",
        active="auth-login",
        extra_context={
            "next_url": safe_next_url(next_url),
            "username": "",
            "error": "",
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_post(request: Request) -> Response:
    form = await read_urlencoded_form(request)
    next_url = safe_next_url(form.get("next", "/"))
    username = _normalize_username(form.get("username", ""))
    password = form.get("password", "")
    error = _GENERIC_LOGIN_ERROR

    try:
        require_valid_csrf(form)
    except HTTPException:
        response = render_template(
            request,
            "login.html",
            title="Login",
            active="auth-login",
            extra_context={"next_url": next_url, "username": username, "error": "This form expired. Please try again."},
        )
        response.status_code = 403
        return response

    if not PTM_AUTH_ENABLED:
        error = "Login is currently disabled."
    elif _login_rate_limited(request, username):
        error = "Too many login attempts. Please try again later."
        _audit_auth(request, "login_rate_limited", False, username=username)
    else:
        try:
            ensure_bootstrap_admin()
            user = get_app_user_by_username(username, include_password=True)
            password_to_check = password[: PTM_AUTH_PASSWORD_MAX_LENGTH + 1]
            password_matches = verify_login_password(password_to_check, user)
            if user and user.get("is_active") and not user.get("is_locked") and password_matches:
                upgrade_password_hash_if_needed(
                    int(user["user_id"]),
                    password_to_check,
                    str(user.get("password_hash", "")),
                )
                record_login_success(int(user["user_id"]))
                response = RedirectResponse(next_url, status_code=303)
                set_auth_cookie(response, int(user["user_id"]), int(user["session_version"]))
                _audit_auth(
                    request,
                    "login_success",
                    True,
                    actor_user_id=int(user["user_id"]),
                    target_user_id=int(user["user_id"]),
                    username=username,
                )
                return response
            if user and user.get("is_active") and not user.get("is_locked"):
                record_login_failure(int(user["user_id"]))
            _record_login_rate_failure(request, username)
            failure_reason = "unknown_user"
            if user:
                if not user.get("is_active"):
                    failure_reason = "inactive"
                elif user.get("is_locked"):
                    failure_reason = "locked"
                else:
                    failure_reason = "invalid_password"
            _audit_auth(
                request,
                "login_failure",
                False,
                target_user_id=int(user["user_id"]) if user else None,
                username=username,
                detail=failure_reason,
            )
        except Exception:
            LOGGER.exception("Login processing failed")
            error = "Login database is temporarily unavailable."

    return render_template(
        request,
        "login.html",
        title="Login",
        active="auth-login",
        extra_context={
            "next_url": next_url,
            "username": username,
            "error": error,
        },
    )


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    user = get_current_user(request)
    form = await read_urlencoded_form(request)
    require_valid_csrf(form, int(user["user_id"]) if user else 0)
    if user:
        try:
            revoke_user_sessions(int(user["user_id"]))
            _audit_auth(
                request,
                "logout_all_sessions",
                True,
                actor_user_id=int(user["user_id"]),
                target_user_id=int(user["user_id"]),
                username=str(user["username"]),
            )
        except Exception:
            LOGGER.exception("Unable to revoke sessions during logout")
    response = RedirectResponse("/", status_code=303)
    clear_auth_cookie(response)
    return response


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user
    return render_user_admin(request)


def _render_agent_settings(
    request: Request,
    *,
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    account_user = get_current_user(request)
    if not account_user:
        raise HTTPException(status_code=401, detail="Sign-in required")
    user_id = int(account_user["user_id"])
    settings = get_user_agent_settings(user_id)
    try:
        status = user_agent_configuration_status(user_id, settings.llm_mode)
        local_settings = get_user_agent_profile_settings(user_id, "local")
        api_settings = get_user_agent_profile_settings(user_id, "api")
        local_status = user_agent_configuration_status(user_id, "local")
        api_status = user_agent_configuration_status(user_id, "api")
    except Exception:
        LOGGER.exception("Unable to read account Agent model configuration status")
        status = {
            "source": "environment",
            "api_key_configured": False,
            "updated_at": None,
        }
        local_settings = replace(
            settings,
            llm_mode="local",
            llm_provider="openai_compatible",
            llm_base_url="http://127.0.0.1:11434/v1",
            llm_model="",
            llm_api_key="",
        )
        api_settings = replace(settings, llm_mode="api")
        local_status = {"source": "environment", "api_key_configured": False}
        api_status = {
            "source": "environment",
            "api_key_configured": bool(api_settings.llm_api_key),
        }
        error = error or "Your saved model configuration is temporarily unavailable."

    model_profiles = {
        "local": {
            "provider": local_settings.llm_provider,
            "base_url": local_settings.llm_base_url,
            "model_name": local_settings.llm_model,
            "llm_timeout": local_settings.llm_timeout,
            "api_key_configured": False,
            "source": local_status.get("source", "environment"),
        },
        "api": {
            "provider": api_settings.llm_provider,
            "base_url": api_settings.llm_base_url,
            "model_name": api_settings.llm_model,
            "llm_timeout": api_settings.llm_timeout,
            "api_key_configured": bool(api_status.get("api_key_configured")),
            "source": api_status.get("source", "environment"),
        },
    }

    return render_template(
        request,
        "account_agent_settings.html",
        title="My Agent Model",
        active="account-agent-settings",
        extra_context={
            "message": message,
            "error": error,
            "agent_settings": settings,
            "config_status": status,
            "api_key_configured": bool(status.get("api_key_configured")),
            "model_profiles": model_profiles,
        },
    )


def _require_agent_settings_enabled() -> None:
    if not AGENT_RUNTIME_ENABLED:
        raise HTTPException(status_code=404, detail="Soybean Assistant is disabled.")


def _model_ids_from_payload(payload: Any) -> list[str]:
    records: Any = []
    if isinstance(payload, dict):
        records = payload.get("data")
        if not isinstance(records, list):
            records = payload.get("models")
    if not isinstance(records, list):
        return []

    model_ids: set[str] = set()
    for record in records:
        if isinstance(record, str):
            model_id = record.strip()
        elif isinstance(record, dict):
            model_id = str(
                record.get("id") or record.get("name") or record.get("model") or ""
            ).strip()
        else:
            continue
        if model_id and len(model_id) <= 200 and not any(
            character in model_id for character in "\r\n\x00"
        ):
            model_ids.add(model_id)
    return sorted(model_ids, key=str.casefold)


@router.get("/account/agent-settings", response_class=HTMLResponse)
async def account_agent_settings(request: Request) -> Response:
    _require_agent_settings_enabled()
    account_user = get_current_user(request)
    if not account_user:
        return login_redirect_response(request)
    return _render_agent_settings(request)


@router.post("/account/agent-settings/models", response_class=JSONResponse)
async def account_agent_models(request: Request) -> JSONResponse:
    _require_agent_settings_enabled()
    account_user = get_current_user(request)
    if not account_user:
        raise HTTPException(status_code=401, detail="Sign-in required.")

    raw_body = await request.body()
    if len(raw_body) > 16_384:
        raise HTTPException(status_code=413, detail="Model discovery request is too large.")
    try:
        payload = json.loads(raw_body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid model discovery request.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid model discovery request.")

    user_id = int(account_user["user_id"])
    require_valid_csrf({"csrf_token": str(payload.get("csrf_token") or "")}, user_id)
    try:
        connection = prepare_user_model_discovery(payload, user_id=user_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    endpoint = f"{connection['base_url'].rstrip('/')}/models"
    headers = {"Accept": "application/json"}
    if connection["api_key"]:
        headers["Authorization"] = f"Bearer {connection['api_key']}"

    response_body = bytearray()
    try:
        timeout = min(float(connection["llm_timeout"]), 30.0)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        ) as client:
            async with client.stream("GET", endpoint, headers=headers) as response:
                if response.status_code in {401, 403}:
                    raise HTTPException(
                        status_code=400,
                        detail="The model service rejected the API key or account permissions.",
                    )
                if response.is_redirect:
                    raise HTTPException(
                        status_code=502,
                        detail="The model service returned an unsupported redirect.",
                    )
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"The model service returned HTTP {response.status_code}.",
                    )
                async for chunk in response.aiter_bytes():
                    response_body.extend(chunk)
                    if len(response_body) > 1_048_576:
                        raise HTTPException(
                            status_code=502,
                            detail="The model list returned by the service is too large.",
                        )
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Model discovery timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to the configured model service.",
        ) from exc

    try:
        provider_payload = json.loads(response_body)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The model service returned an invalid model list.",
        ) from exc
    models = _model_ids_from_payload(provider_payload)
    if not models:
        raise HTTPException(
            status_code=502,
            detail="The model service did not return any available model IDs.",
        )
    return JSONResponse({"models": models, "count": len(models)})


@router.post("/account/agent-settings", response_class=HTMLResponse)
async def account_update_agent_settings(request: Request) -> Response:
    _require_agent_settings_enabled()
    account_user = get_current_user(request)
    if not account_user:
        return login_redirect_response(request)

    form = await read_urlencoded_form(request)
    user_id = int(account_user["user_id"])
    require_valid_csrf(form, user_id)
    mode = form.get("mode", "").strip().lower()
    new_api_key = form.get("api_key", "").strip()

    try:
        saved = save_user_agent_configuration(
            {
                "mode": mode,
                "provider": form.get("provider", ""),
                "base_url": form.get("base_url", ""),
                "model_name": form.get("model_name", ""),
                "api_key": new_api_key,
                "llm_timeout": form.get("llm_timeout", "30"),
            },
            user_id=user_id,
        )
        _audit_auth(
            request,
            "user_agent_model_config_update",
            True,
            actor_user_id=user_id,
            target_user_id=user_id,
            username=str(account_user.get("username", "")),
            detail=f"{saved['mode']}:{saved['provider']}:{saved['model_name']}",
        )
        return _render_agent_settings(
            request,
            message="Agent model settings saved. New Agent requests will use this configuration.",
        )
    except (ValueError, RuntimeError) as exc:
        _audit_auth(
            request,
            "user_agent_model_config_update",
            False,
            actor_user_id=user_id,
            target_user_id=user_id,
            username=str(account_user.get("username", "")),
            detail="validation_or_storage_error",
        )
        return _render_agent_settings(request, error=str(exc))
    except Exception:
        LOGGER.exception("Unable to update Agent model settings")
        return _render_agent_settings(
            request,
            error="Unable to save Agent model settings. Please check the database and server logs.",
        )


@router.post("/admin/users/create", response_class=HTMLResponse)
async def admin_create_user(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await read_urlencoded_form(request)
    require_valid_csrf(form, int(admin_user["user_id"]))
    try:
        ok, msg = create_app_user(
            form.get("username", ""),
            form.get("password", ""),
            form.get("role", AUTH_ROLE_TESTER),
            "can_download" in form,
        )
        created_user = get_app_user_by_username(form.get("username", "")) if ok else None
        _audit_auth(
            request,
            "user_create",
            ok,
            actor_user_id=int(admin_user["user_id"]),
            target_user_id=int(created_user["user_id"]) if created_user else None,
            username=form.get("username", ""),
            detail=form.get("role", AUTH_ROLE_TESTER),
        )
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        LOGGER.exception("Unable to create user")
        return render_user_admin(request, error="Unable to create user. Please check the database.")


@router.post("/admin/users/update", response_class=HTMLResponse)
async def admin_update_user(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await read_urlencoded_form(request)
    require_valid_csrf(form, int(admin_user["user_id"]))
    try:
        target_user_id = int(form.get("user_id", "0") or 0)
    except ValueError:
        target_user_id = 0

    try:
        ok, msg = update_app_user(
            target_user_id=target_user_id,
            acting_user_id=int(admin_user["user_id"]),
            role=form.get("role", AUTH_ROLE_TESTER),
            can_download="can_download" in form,
            is_active="is_active" in form,
            new_password=form.get("new_password", "").strip(),
        )
        _audit_auth(
            request,
            "user_update",
            ok,
            actor_user_id=int(admin_user["user_id"]),
            target_user_id=target_user_id or None,
            detail="password_reset" if form.get("new_password", "").strip() else "permissions",
        )
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        LOGGER.exception("Unable to update user")
        return render_user_admin(request, error="Unable to update user. Please check the database.")


@router.post("/admin/users/delete", response_class=HTMLResponse)
async def admin_delete_user(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await read_urlencoded_form(request)
    require_valid_csrf(form, int(admin_user["user_id"]))
    try:
        target_user_id = int(form.get("user_id", "0") or 0)
    except ValueError:
        target_user_id = 0

    try:
        target_user = get_app_user_by_id(target_user_id)
        ok, msg = delete_app_user(target_user_id, int(admin_user["user_id"]))
        _audit_auth(
            request,
            "user_delete",
            ok,
            actor_user_id=int(admin_user["user_id"]),
            target_user_id=target_user_id or None,
            username=str(target_user.get("username", "")) if target_user else "",
        )
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        LOGGER.exception("Unable to delete user")
        return render_user_admin(request, error="Unable to delete user. Please check the database.")


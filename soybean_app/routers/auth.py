import json
import logging
import math
import threading
import time
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


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


def _login_lockout_message() -> str:
    return f"Too many failed attempts. Account locked for {PTM_AUTH_LOCKOUT_MINUTES} minutes."


def _login_password_error_message(failed_count: int) -> str:
    remaining = max(0, PTM_AUTH_MAX_FAILED_ATTEMPTS - failed_count)
    if remaining <= 0:
        return _login_lockout_message()
    attempt_label = "attempt" if remaining == 1 else "attempts"
    return (
        f"Invalid password. {remaining} {attempt_label} remaining before a "
        f"{PTM_AUTH_LOCKOUT_MINUTES}-minute lockout."
    )


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
    error = "Invalid username or password."

    if not PTM_AUTH_ENABLED:
        error = "Login is currently disabled."
    else:
        try:
            ensure_bootstrap_admin()
            user = get_app_user_by_username(username, include_password=True)
            if not user or not user.get("is_active"):
                error = "Invalid user."
            elif user.get("is_locked"):
                error = _login_lockout_message()
            elif _verify_password(password, str(user.get("password_hash", ""))):
                record_login_success(int(user["user_id"]))
                response = RedirectResponse(next_url, status_code=303)
                set_auth_cookie(response, int(user["user_id"]))
                return response
            else:
                failed_count = record_login_failure(int(user["user_id"]))
                error = _login_password_error_message(failed_count)
        except Exception:
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


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
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
    try:
        ok, msg = create_app_user(
            form.get("username", ""),
            form.get("password", ""),
            form.get("role", AUTH_ROLE_TESTER),
            "can_download" in form,
        )
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        return render_user_admin(request, error="Unable to create user. Please check the database.")


@router.post("/admin/users/update", response_class=HTMLResponse)
async def admin_update_user(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await read_urlencoded_form(request)
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
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        return render_user_admin(request, error="Unable to update user. Please check the database.")


@router.post("/admin/users/delete", response_class=HTMLResponse)
async def admin_delete_user(request: Request) -> Response:
    admin_user = require_admin_user(request)
    if isinstance(admin_user, RedirectResponse):
        return admin_user

    form = await read_urlencoded_form(request)
    try:
        target_user_id = int(form.get("user_id", "0") or 0)
    except ValueError:
        target_user_id = 0

    try:
        ok, msg = delete_app_user(target_user_id, int(admin_user["user_id"]))
        return render_user_admin(request, message=msg if ok else "", error="" if ok else msg)
    except Exception:
        return render_user_admin(request, error="Unable to delete user. Please check the database.")


import urllib.parse
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from soybean_app.services import *
from soybean_app.services.agent import AGENT_RUNTIME_ENABLED

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["static_url"] = lambda request, path: request.url_for("static", path=path)
templates.env.globals["route_url"] = lambda request, route_name: request.url_for(route_name)
templates.env.globals["external_id_tokens"] = external_id_tokens
templates.env.globals["phytozome_gene_url"] = phytozome_gene_url
templates.env.globals["uniprot_entry_url"] = uniprot_entry_url


def render_template(
    request: Request,
    template_name: str,
    *,
    title: str,
    active: str,
    extra_context: dict[str, Any] | None = None,
) -> HTMLResponse:
    current_user = get_current_user(request)
    context: dict[str, Any] = {
        "request": request,
        "title": title,
        "active": active,
        "nav_items": NAV_ITEMS,
        "search_menu": SEARCH_MENU,
        "analysis_menu": ANALYSIS_MENU,
        "data_menu": DATA_MENU,
        "agent_runtime_enabled": AGENT_RUNTIME_ENABLED,
        "auth_enabled": PTM_AUTH_ENABLED,
        "current_user": current_user,
        "user_can_download": current_user_can_download(request),
        "downloads_public_enabled": PTM_DOWNLOADS_ENABLED,
        "downloads_enabled": current_downloads_enabled(request),
        "downloads_disabled_message": DOWNLOADS_DISABLED_MESSAGE,
        "csrf_token": create_csrf_token(int(current_user["user_id"]) if current_user else 0),
        "password_min_length": PTM_AUTH_PASSWORD_MIN_LENGTH,
        "password_max_length": PTM_AUTH_PASSWORD_MAX_LENGTH,
    }
    if extra_context:
        context.update(extra_context)
    try:
        # Starlette/FastAPI newer signature
        return templates.TemplateResponse(request=request, name=template_name, context=context)
    except TypeError:
        # Backward-compatible fallback for older signature
        return templates.TemplateResponse(template_name, context=context)


def render_page(request: Request, page_key: str, active_key: str) -> HTMLResponse:
    page = PAGES[page_key]
    return render_template(
        request,
        "simple_page.html",
        title=page["title"],
        active=active_key,
        extra_context={"page": page},
    )


async def read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8", errors="replace")
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def safe_next_url(value: str, fallback: str = "/") -> str:
    candidate = str(value or "").strip()
    if not candidate.startswith("/") or candidate.startswith("//"):
        return fallback
    return candidate


def set_auth_cookie(response: Response, user_id: int, session_version: int) -> None:
    max_age = PTM_AUTH_SESSION_DAYS * 24 * 60 * 60
    response.set_cookie(
        PTM_AUTH_COOKIE_NAME,
        create_session_token(user_id, session_version),
        max_age=max_age,
        httponly=True,
        secure=PTM_AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        PTM_AUTH_COOKIE_NAME,
        httponly=True,
        secure=PTM_AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def require_valid_csrf(form: dict[str, str], user_id: int = 0) -> None:
    if not verify_csrf_token(form.get("csrf_token", ""), user_id):
        raise HTTPException(status_code=403, detail="Invalid or expired form token. Please refresh the page and try again.")


def login_redirect_response(request: Request) -> RedirectResponse:
    next_url = safe_next_url(str(request.url.path))
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    return RedirectResponse(f"/login?next={urllib.parse.quote(next_url)}", status_code=303)


def require_admin_user(request: Request) -> dict[str, Any] | RedirectResponse:
    user = get_current_user(request)
    if not user:
        return login_redirect_response(request)
    if user.get("role") != AUTH_ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return user


def render_user_admin(
    request: Request,
    *,
    message: str = "",
    error: str = "",
) -> HTMLResponse:
    try:
        ensure_bootstrap_admin()
        users = list_app_users()
    except Exception:
        users = []
        error = error or "User database is temporarily unavailable."

    return render_template(
        request,
        "admin_users.html",
        title="User Management",
        active="auth-users",
        extra_context={
            "users": users,
            "message": message,
            "error": error,
            "roles": [AUTH_ROLE_TESTER, AUTH_ROLE_ADMIN],
        },
    )


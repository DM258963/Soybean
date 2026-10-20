import mimetypes
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from soybean_app.routers import auth, agent, home, pages, search
from soybean_app.research_agent.graph import close_agent_runtime, initialize_agent_runtime
from soybean_app.research_agent.configuration import initialize_user_agent_configuration_storage
from soybean_app.services import (
    PTM_AUTH_COOKIE_NAME,
    PTM_AUTH_COOKIE_SECURE,
    STATIC_DIR,
    close_database_pool,
    ensure_bootstrap_admin,
    initialize_database_pool,
    refresh_home_ptm_stats_cache,
    validate_auth_security_config,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database_pool()
    try:
        initialize_user_agent_configuration_storage()
        try:
            ensure_bootstrap_admin()
        except Exception:
            pass
        try:
            refresh_home_ptm_stats_cache()
        except Exception:
            pass

        initialize_agent_runtime()
        yield
    finally:
        close_agent_runtime()
        close_database_pool()


def create_app() -> FastAPI:
    validate_auth_security_config()
    app = FastAPI(title="Soybean PTM Viewer 1.0", lifespan=lifespan)
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'",
        )
        if PTM_AUTH_COOKIE_SECURE and request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        is_sensitive_page = (
            request.url.path == "/login"
            or request.url.path == "/logout"
            or request.url.path.startswith("/admin/")
            or (PTM_AUTH_COOKIE_NAME in request.cookies and not request.url.path.startswith("/static/"))
        )
        if is_sensitive_page:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    app.include_router(auth.router)
    app.include_router(home.router)
    app.include_router(agent.router)
    app.include_router(search.router)
    app.include_router(pages.router)
    return app


app = create_app()

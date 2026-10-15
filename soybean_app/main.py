import mimetypes

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from soybean_app.routers import auth, hermes, home, pages, search
from soybean_app.services import STATIC_DIR, close_database_pool, ensure_bootstrap_admin, refresh_home_ptm_stats_cache


def create_app() -> FastAPI:
    app = FastAPI(title="Soybean PTM Viewer 1.0")
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.on_event("shutdown")
    def close_db_pool() -> None:
        close_database_pool()

    @app.on_event("startup")
    def warm_home_stats_on_startup() -> None:
        try:
            ensure_bootstrap_admin()
        except Exception:
            pass
        try:
            refresh_home_ptm_stats_cache()
        except Exception:
            pass

    app.include_router(auth.router)
    app.include_router(home.router)
    app.include_router(hermes.router)
    app.include_router(search.router)
    app.include_router(pages.router)
    return app


app = create_app()

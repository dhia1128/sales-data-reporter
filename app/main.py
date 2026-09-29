import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import api, web
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.exceptions import AppError
from app.services import reports

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    app.include_router(web.router)
    app.include_router(api.router)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        # JSON for API clients, the upload page with a message for browsers
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": exc.message}, status_code=exc.status_code)
        with SessionLocal() as db:
            recent = reports.list_reports(db, 10)
        return web.templates.TemplateResponse(
            request, "index.html", {"reports": recent, "error": exc.message}, status_code=exc.status_code
        )

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    return app


app = create_app()

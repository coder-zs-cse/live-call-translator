"""FastAPI application entry point.

v1 runs the control plane and the media plane in one process - see docs/PLAN.md
section 10. The split into separate deployables is deliberately deferred until
one call works end to end.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError, RoomNotFoundError
from app.core.logging import configure_logging, get_logger
from app.providers.registry import build_providers

logger = get_logger(__name__)

#: Domain exception to HTTP status. The API layer is the only place allowed to
#: know about status codes, so the mapping lives here rather than in services.
_STATUS_BY_ERROR: dict[type[AppError], int] = {
    RoomNotFoundError: 404,
}
_DEFAULT_ERROR_STATUS = 400


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.app_env)
    logger.info("starting", environment=settings.app_env.value)

    app.state.providers = build_providers(settings)
    try:
        yield
    finally:
        await app.state.providers.aclose()
        logger.info("stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Live Call Translator",
        version="0.1.0",
        lifespan=lifespan,
        # No interactive docs in production: the admin surface is not public.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not settings.is_production else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        status = _STATUS_BY_ERROR.get(type(exc), _DEFAULT_ERROR_STATUS)
        logger.warning("domain_error", code=exc.code, message=exc.message)
        return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message})

    app.include_router(api_router)
    return app


app = create_app()

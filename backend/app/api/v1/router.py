"""v1 API surface. Routers are registered here and nowhere else."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health, ws, xml

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(xml.router)
api_router.include_router(ws.router)

"""Health check DTOs."""

from __future__ import annotations

from pydantic import BaseModel

from app.core.enums import AppEnv


class DependencyHealth(BaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    environment: AppEnv
    version: str
    dependencies: list[DependencyHealth]

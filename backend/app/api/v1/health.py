"""Health and readiness.

Liveness is deliberately dumb: it must not depend on Postgres, or a database
blip takes the process down instead of shedding traffic.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SettingsDep
from app.schemas.health import DependencyHealth, HealthResponse

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    checks = [
        DependencyHealth(
            name="sarvam_api_key",
            healthy=bool(settings.sarvam.api_key.get_secret_value().strip()),
            detail="configured" if settings.sarvam.api_key.get_secret_value() else "missing",
        ),
        DependencyHealth(
            name="vobiz_public_base_url",
            healthy=settings.vobiz.public_base_url.startswith("http"),
            detail=settings.vobiz.public_base_url,
        ),
    ]
    return HealthResponse(
        status="ok" if all(c.healthy for c in checks) else "degraded",
        environment=settings.app_env,
        version=VERSION,
        dependencies=checks,
    )

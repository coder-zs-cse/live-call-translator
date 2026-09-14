"""Shared HTTP plumbing for every Sarvam endpoint.

One place that knows the auth header, the base URL and how a Sarvam error
becomes a domain exception — so the individual services stay about their own
request shape.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from app.core.config import SarvamSettings
from app.core.exceptions import ProviderError

PROVIDER_NAME = "sarvam"
_AUTH_HEADER = "api-subscription-key"


class SarvamHttpClient:
    """Thin wrapper over httpx. Owns the connection pool for its lifetime."""

    def __init__(self, settings: SarvamSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            headers={_AUTH_HEADER: settings.api_key.get_secret_value()},
        )

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(PROVIDER_NAME, f"request to {path} failed: {exc}") from exc

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise ProviderError(
                PROVIDER_NAME,
                f"{path} returned {response.status_code}: {response.text[:400]}",
                status_code=response.status_code,
            )

        body: dict[str, Any] = response.json()
        return body

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SarvamHttpClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

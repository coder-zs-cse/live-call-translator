"""Shared HTTP plumbing for every Sarvam endpoint.

One place that knows the auth header, the base URL, how a Sarvam error becomes a
domain exception, and how transient failures are retried - so the individual
services stay about their own request shape.
"""

from __future__ import annotations

import asyncio
import secrets
from types import TracebackType
from typing import Any

import httpx

from app.core.config import SarvamSettings
from app.core.exceptions import ProviderError
from app.core.logging import get_logger

logger = get_logger(__name__)

PROVIDER_NAME = "sarvam"
_AUTH_HEADER = "api-subscription-key"

#: Worth retrying: rate limiting and transient gateway failures. A 400 or 401 is
#: our bug and retrying it just wastes time inside a live call.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


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
        last_error: str = "no attempts made"

        for attempt in range(self._settings.max_retries + 1):
            try:
                response = await self._client.post(path, json=payload)
            except httpx.HTTPError as exc:
                last_error = f"request to {path} failed: {exc}"
                if attempt == self._settings.max_retries:
                    raise ProviderError(PROVIDER_NAME, last_error) from exc
                await self._sleep_before_retry(attempt, retry_after=None)
                continue

            if response.status_code < httpx.codes.BAD_REQUEST:
                body: dict[str, Any] = response.json()
                return body

            last_error = f"{path} returned {response.status_code}: {response.text[:400]}"
            if (
                response.status_code not in _RETRYABLE_STATUS
                or attempt == self._settings.max_retries
            ):
                raise ProviderError(PROVIDER_NAME, last_error, status_code=response.status_code)

            logger.warning(
                "sarvam_retrying",
                path=path,
                status=response.status_code,
                attempt=attempt + 1,
                of=self._settings.max_retries,
            )
            await self._sleep_before_retry(attempt, retry_after=response.headers.get("retry-after"))

        raise ProviderError(PROVIDER_NAME, last_error)

    async def _sleep_before_retry(self, attempt: int, *, retry_after: str | None) -> None:
        """Exponential backoff with jitter, or the server's own advice.

        Jitter matters because a pipeline translates both directions of a call
        at once; without it two retries collide and get rate limited together.
        """
        if retry_after:
            try:
                await asyncio.sleep(min(float(retry_after), self._settings.max_backoff_seconds))
                return
            except ValueError:
                pass  # Retry-After can be an HTTP date; fall through to backoff.

        base = self._settings.retry_backoff_seconds * (2**attempt)
        jitter = secrets.randbelow(100) / 100.0
        await asyncio.sleep(min(base + jitter, self._settings.max_backoff_seconds))

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

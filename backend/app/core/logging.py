"""Structured logging.

Every log line carries call_id/leg_id where one is in scope, because the first
question about any recorded problem is "which call?".
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.enums import AppEnv


def configure_logging(level: str, env: AppEnv) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    # JSON in prod so it is greppable by a log aggregator; colours locally.
    processors.append(
        structlog.processors.JSONRenderer()
        if env is AppEnv.PROD
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]

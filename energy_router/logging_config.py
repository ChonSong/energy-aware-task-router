"""Centralized structlog configuration for structured logging.

Call ``configure_logging()`` once at process startup to set up
timestamps, log levels, stack traces for errors, and JSON or
dev-friendly console output.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(
    *,
    level: str = "INFO",
    log_format: str = "json",
) -> None:
    """Configure structlog (and stdlib logging) for the whole process.

    Parameters
    ----------
    level:
        Log level (``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``).
    log_format:
        ``"json"`` for JSON lines (production) or ``"dev"`` for
        coloured human-readable output (local development).
    """
    level_upper = level.upper().strip()
    log_level = getattr(logging, level_upper, logging.INFO)

    # Shared processors that run in both dev and json mode
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.set_exc_info,
        structlog.stdlib.ExtraAdder(),
    ]

    if log_format == "dev":
        processors: list[structlog.types.Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route structlog messages through standard logging so they respect
    # the same level configuration and handlers.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

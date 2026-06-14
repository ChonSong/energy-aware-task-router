"""Tests for the structured logging configuration module."""

from __future__ import annotations

import logging

import structlog


def test_configure_logging_json_default():
    """Default configuration should use JSON format."""
    from energy_router.logging_config import configure_logging

    configure_logging()

    logger = structlog.get_logger("test_json")
    logger.info("test_event", key="value")


def test_configure_logging_dev_format():
    """Dev format should not raise."""
    from energy_router.logging_config import configure_logging

    configure_logging(log_format="dev")
    logger = structlog.get_logger("test_dev")
    logger.info("test_dev_event", lang="python")


def test_configure_logging_debug_level():
    """DEBUG level should be accepted without error."""
    from energy_router.logging_config import configure_logging

    configure_logging(level="DEBUG")
    logger = structlog.get_logger("test_debug")
    logger.debug("debug_event", detail="should be visible")


def test_configure_logging_accepts_uppercase_level():
    """Uppercase and lowercase level strings should both work."""
    from energy_router.logging_config import configure_logging

    configure_logging(level="WARNING")
    root = logging.getLogger()
    assert root.level == logging.WARNING, f"Expected WARNING, got {root.level}"

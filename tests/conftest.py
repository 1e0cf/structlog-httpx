"""Shared fixtures for structlog-httpx tests."""

from __future__ import annotations

import pytest
import structlog_httpx


@pytest.fixture(autouse=True)
def _cleanup_global_instrumentation():
    """Ensure global instrumentation is cleaned up after each test."""
    yield
    structlog_httpx.uninstall()
    # Reset internal flag
    structlog_httpx._installed = False


class LogCapture:
    """Simple log capture that records structlog events."""

    def __init__(self):
        self.events: list[dict] = []

    def __getattr__(self, name: str):
        if name in ("info", "error", "debug", "warning", "critical"):

            def log_method(event: str, **kw):
                self.events.append({"_event": event, "_level": name, **kw})

            return log_method
        raise AttributeError(name)

    def clear(self):
        self.events.clear()


@pytest.fixture
def log_capture():
    return LogCapture()

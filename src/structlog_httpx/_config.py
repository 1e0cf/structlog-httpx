"""Logging configuration for structlog-httpx."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LoggingConfig:
    """Controls what data is collected from HTTP requests/responses.

    Processors control how the collected data is processed before logging.
    """

    log_request_body: bool = True
    log_response_body: bool = True
    log_request_headers: bool = True
    log_response_headers: bool = False

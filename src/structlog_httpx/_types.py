"""Type definitions for structlog-httpx."""

from __future__ import annotations

from typing import TypedDict, Union

from structlog.stdlib import BoundLogger


class HttpxLogEvent(TypedDict, total=False):
    """Structured log event for an HTTP request/response cycle."""

    # Always present
    method: str
    url: str
    duration: float
    level: str

    # Present on successful response
    status_code: int
    content_length: int

    # Client identification
    client_name: str

    # Optional (controlled by LoggingConfig)
    request_headers: dict[str, str]
    response_headers: dict[str, str]
    request_body: str
    response_body: str

    # Error fields (present on exception)
    error: str
    error_type: str


Logger = Union[BoundLogger, object]

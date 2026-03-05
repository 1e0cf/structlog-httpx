"""Built-in processors for structlog-httpx."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Set

import httpx

from ._constants import (
    DEFAULT_LOGGABLE_CONTENT_TYPES,
    DEFAULT_MAX_BODY_SIZE,
    DEFAULT_SENSITIVE_HEADERS,
)
from ._types import HttpxLogEvent


class BaseProcessor(ABC):
    """Base class for structlog-httpx log processors.

    Subclass and implement ``process()`` to create custom processors.

    Example::

        class AddTraceId(BaseProcessor):
            def process(self, request, response, event):
                event["trace_id"] = get_current_trace_id()
                return event
    """

    @abstractmethod
    def process(
        self,
        request: httpx.Request,
        response: httpx.Response | None,
        event: HttpxLogEvent,
    ) -> HttpxLogEvent | None:
        """Process the log event before emission.

        Args:
            request: The outgoing HTTP request.
            response: The HTTP response, or None if the request failed.
            event: The log event dict to modify.

        Returns:
            The modified event dict, or None to suppress logging entirely.
        """
        ...


class RedactSensitiveHeaders(BaseProcessor):
    """Replaces values of sensitive headers with a redaction marker."""

    def __init__(
        self,
        sensitive: Set[str] = DEFAULT_SENSITIVE_HEADERS,
        replacement: str = "[REDACTED]",
    ):
        self._sensitive = frozenset(h.lower() for h in sensitive)
        self._replacement = replacement

    def process(
        self,
        request: httpx.Request,
        response: httpx.Response | None,
        event: HttpxLogEvent,
    ) -> HttpxLogEvent | None:
        for key in ("request_headers", "response_headers"):
            headers = event.get(key)  # type: ignore[literal-required]
            if headers is not None:
                event[key] = {  # type: ignore[literal-required]
                    k: self._replacement if k.lower() in self._sensitive else v
                    for k, v in headers.items()
                }
        return event


class FilterBodyByContentType(BaseProcessor):
    """Removes response body from the log event if content-type is not loggable."""

    def __init__(self, allowed: Set[str] = DEFAULT_LOGGABLE_CONTENT_TYPES):
        self._allowed = frozenset(ct.lower() for ct in allowed)

    def process(
        self,
        request: httpx.Request,
        response: httpx.Response | None,
        event: HttpxLogEvent,
    ) -> HttpxLogEvent | None:
        if "response_body" not in event or response is None:
            return event

        content_type = response.headers.get("content-type", "")
        mime = content_type.split(";")[0].strip().lower()
        if mime not in self._allowed:
            del event["response_body"]  # type: ignore[misc]

        return event


class TruncateBodies(BaseProcessor):
    """Truncates request and response bodies that exceed max size."""

    def __init__(self, max_size: int = DEFAULT_MAX_BODY_SIZE):
        self._max_size = max_size

    def process(
        self,
        request: httpx.Request,
        response: httpx.Response | None,
        event: HttpxLogEvent,
    ) -> HttpxLogEvent | None:
        for key in ("request_body", "response_body"):
            body = event.get(key)  # type: ignore[literal-required]
            if body is not None and isinstance(body, str) and len(body) > self._max_size:
                event[key] = (  # type: ignore[literal-required]
                    body[: self._max_size] + f"... ({len(body)} chars) [truncated]"
                )
        return event


def build_default_processors() -> list[BaseProcessor]:
    """Create the default processor chain."""
    return [
        RedactSensitiveHeaders(),
        FilterBodyByContentType(),
        TruncateBodies(),
    ]

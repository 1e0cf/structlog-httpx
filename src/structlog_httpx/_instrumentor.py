"""Core instrumentation logic: transport wrappers and global patching."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import structlog

from ._config import LoggingConfig
from ._types import HttpxLogEvent, Logger
from .processors import BaseProcessor, build_default_processors

if TYPE_CHECKING:
    pass


def _build_event(
    *,
    request: httpx.Request,
    response: httpx.Response | None,
    duration: float,
    config: LoggingConfig,
    client_name: str | None,
) -> HttpxLogEvent:
    """Build the base log event dict from request/response data."""
    event: HttpxLogEvent = {
        "method": request.method,
        "url": str(request.url),
        "duration": round(duration, 4),
    }

    if client_name:
        event["client_name"] = client_name

    if response is not None:
        event["status_code"] = response.status_code
        event["level"] = "error" if response.status_code >= 400 else "info"

        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                event["content_length"] = int(content_length)
            except ValueError:
                pass

        if config.log_response_headers:
            event["response_headers"] = dict(response.headers)

        if config.log_response_body:
            try:
                body_bytes = response.content
                event["response_body"] = body_bytes.decode("utf-8", errors="replace")
            except httpx.ResponseNotRead:
                pass

    if config.log_request_headers:
        event["request_headers"] = dict(request.headers)

    if config.log_request_body:
        try:
            event["request_body"] = request.content.decode("utf-8", errors="replace")
        except Exception:
            pass

    return event


def _build_error_event(
    *,
    request: httpx.Request,
    duration: float,
    exc: BaseException,
    client_name: str | None,
) -> HttpxLogEvent:
    """Build a log event for a failed request (exception)."""
    event: HttpxLogEvent = {
        "method": request.method,
        "url": str(request.url),
        "duration": round(duration, 4),
        "level": "error",
        "error": str(exc),
        "error_type": type(exc).__name__,
    }
    if client_name:
        event["client_name"] = client_name
    return event


def _run_processors(
    processors: list[BaseProcessor],
    request: httpx.Request,
    response: httpx.Response | None,
    event: HttpxLogEvent,
) -> HttpxLogEvent | None:
    """Run event through the processor chain. Returns None if suppressed."""
    for processor in processors:
        event = processor.process(request, response, event)  # type: ignore[assignment]
        if event is None:
            return None
    return event


def _emit_log(logger: Logger, event: HttpxLogEvent, event_name: str) -> None:
    """Emit the log event at the appropriate level."""
    level = event.pop("level", "info")  # type: ignore[misc]
    log_method = getattr(logger, level, None) or getattr(logger, "info")
    log_method(event_name, **event)


# ---------------------------------------------------------------------------
# Transport wrappers (for per-client instrumentation)
# ---------------------------------------------------------------------------


class StructlogTransport(httpx.BaseTransport):
    """Sync transport wrapper that logs requests via structlog."""

    def __init__(
        self,
        transport: httpx.BaseTransport,
        *,
        name: str | None = None,
        config: LoggingConfig | None = None,
        processors: list[BaseProcessor] | None = None,
        logger: Logger | None = None,
    ):
        self._wrapped_transport = transport
        self._name = name
        self._config = config or LoggingConfig()
        self._processors = processors if processors is not None else build_default_processors()
        self._logger = logger or structlog.get_logger("structlog_httpx")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        _mark_request(request)
        start = time.perf_counter()
        try:
            response = self._wrapped_transport.handle_request(request)
        except Exception as exc:
            duration = time.perf_counter() - start
            event = _build_error_event(
                request=request, duration=duration, exc=exc, client_name=self._name,
            )
            event = _run_processors(self._processors, request, None, event)
            if event is not None:
                _emit_log(self._logger, event, "http_request_failed")
            raise

        duration = time.perf_counter() - start

        # Read response body into memory if configured (needed before _build_event)
        if self._config.log_response_body:
            try:
                response.read()
            except Exception:
                pass

        event = _build_event(
            request=request,
            response=response,
            duration=duration,
            config=self._config,
            client_name=self._name,
        )
        event = _run_processors(self._processors, request, response, event)
        if event is not None:
            _emit_log(self._logger, event, "http_request_finished")

        return response

    def close(self) -> None:
        self._wrapped_transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AsyncStructlogTransport(httpx.AsyncBaseTransport):
    """Async transport wrapper that logs requests via structlog."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        *,
        name: str | None = None,
        config: LoggingConfig | None = None,
        processors: list[BaseProcessor] | None = None,
        logger: Logger | None = None,
    ):
        self._wrapped_transport = transport
        self._name = name
        self._config = config or LoggingConfig()
        self._processors = processors if processors is not None else build_default_processors()
        self._logger = logger or structlog.get_logger("structlog_httpx")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        _mark_request(request)
        start = time.perf_counter()
        try:
            response = await self._wrapped_transport.handle_async_request(request)
        except Exception as exc:
            duration = time.perf_counter() - start
            event = _build_error_event(
                request=request, duration=duration, exc=exc, client_name=self._name,
            )
            event = _run_processors(self._processors, request, None, event)
            if event is not None:
                _emit_log(self._logger, event, "http_request_failed")
            raise

        duration = time.perf_counter() - start

        if self._config.log_response_body:
            try:
                await response.aread()
            except Exception:
                pass

        event = _build_event(
            request=request,
            response=response,
            duration=duration,
            config=self._config,
            client_name=self._name,
        )
        event = _run_processors(self._processors, request, response, event)
        if event is not None:
            _emit_log(self._logger, event, "http_request_finished")

        return response

    async def aclose(self) -> None:
        await self._wrapped_transport.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()


# ---------------------------------------------------------------------------
# Global instrumentation via wrapt
# ---------------------------------------------------------------------------

# Stores the global config so wrapt wrappers can access it
_global_state: dict | None = None

# Marker attribute set on requests being processed by a per-client transport
# to prevent double-logging when global wrapt wrapper also fires.
_INSTRUMENTED_ATTR = "_structlog_httpx_handled"


def _mark_request(request: httpx.Request) -> None:
    """Mark a request as being handled by a per-client transport."""
    setattr(request, _INSTRUMENTED_ATTR, True)


def _is_request_handled(request: httpx.Request) -> bool:
    """Check if a request is already being handled by a per-client transport."""
    return getattr(request, _INSTRUMENTED_ATTR, False)


def _global_sync_wrapper(wrapped, instance, args, kwargs):
    """wrapt wrapper for HTTPTransport.handle_request."""
    if _global_state is None:
        return wrapped(*args, **kwargs)

    request = args[0] if args and isinstance(args[0], httpx.Request) else None
    if request is None or _is_request_handled(request):
        return wrapped(*args, **kwargs)

    config = _global_state["config"]
    processors = _global_state["processors"]
    logger = _global_state["logger"]

    start = time.perf_counter()
    try:
        response = wrapped(*args, **kwargs)
    except Exception as exc:
        duration = time.perf_counter() - start
        event = _build_error_event(request=request, duration=duration, exc=exc, client_name=None)
        event = _run_processors(processors, request, None, event)
        if event is not None:
            _emit_log(logger, event, "http_request_failed")
        raise

    duration = time.perf_counter() - start

    if config.log_response_body:
        try:
            response.read()
        except Exception:
            pass

    event = _build_event(
        request=request, response=response, duration=duration,
        config=config, client_name=None,
    )
    event = _run_processors(processors, request, response, event)
    if event is not None:
        _emit_log(logger, event, "http_request_finished")

    return response


async def _global_async_wrapper(wrapped, instance, args, kwargs):
    """wrapt wrapper for AsyncHTTPTransport.handle_async_request."""
    if _global_state is None:
        return await wrapped(*args, **kwargs)

    request = args[0] if args and isinstance(args[0], httpx.Request) else None
    if request is None or _is_request_handled(request):
        return await wrapped(*args, **kwargs)

    config = _global_state["config"]
    processors = _global_state["processors"]
    logger = _global_state["logger"]

    start = time.perf_counter()
    try:
        response = await wrapped(*args, **kwargs)
    except Exception as exc:
        duration = time.perf_counter() - start
        event = _build_error_event(request=request, duration=duration, exc=exc, client_name=None)
        event = _run_processors(processors, request, None, event)
        if event is not None:
            _emit_log(logger, event, "http_request_failed")
        raise

    duration = time.perf_counter() - start

    if config.log_response_body:
        try:
            await response.aread()
        except Exception:
            pass

    event = _build_event(
        request=request, response=response, duration=duration,
        config=config, client_name=None,
    )
    event = _run_processors(processors, request, response, event)
    if event is not None:
        _emit_log(logger, event, "http_request_finished")

    return response

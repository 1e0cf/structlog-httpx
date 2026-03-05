"""structlog-httpx: Structured logging for outgoing HTTPX requests."""

from __future__ import annotations

import httpx
import structlog
import wrapt

from ._config import LoggingConfig
from ._instrumentor import (
    AsyncStructlogTransport,
    StructlogTransport,
    _global_async_wrapper,
    _global_sync_wrapper,
)
from ._types import Logger
from .processors import (
    BaseProcessor,
    FilterBodyByContentType,
    RedactSensitiveHeaders,
    TruncateBodies,
    build_default_processors,
)

__all__ = [
    # Public API
    "install",
    "uninstall",
    "instrument_client",
    "uninstrument_client",
    # Configuration
    "LoggingConfig",
    # Transport wrappers (advanced)
    "StructlogTransport",
    "AsyncStructlogTransport",
    # Processors
    "BaseProcessor",
    "RedactSensitiveHeaders",
    "FilterBodyByContentType",
    "TruncateBodies",
]

_installed: bool = False


def _resolve_processors(
    user_processors: list[BaseProcessor] | None,
    include_defaults: bool,
) -> list[BaseProcessor]:
    """Build the final processor chain."""
    chain: list[BaseProcessor] = []
    if include_defaults:
        chain.extend(build_default_processors())
    if user_processors:
        chain.extend(user_processors)
    return chain


def install(
    *,
    config: LoggingConfig | None = None,
    processors: list[BaseProcessor] | None = None,
    include_default_processors: bool = True,
    logger: Logger | None = None,
) -> None:
    """Globally instrument httpx to log all outgoing requests.

    This patches ``httpx.HTTPTransport`` and ``httpx.AsyncHTTPTransport``
    so that every httpx client automatically logs requests via structlog.

    Args:
        config: Controls what data is collected (headers, body).
        processors: Additional processors appended after defaults.
        include_default_processors: Whether to include built-in processors
            (redact headers, filter by content-type, truncate bodies).
        logger: Custom structlog logger instance.

    Example::

        # Zero-config
        install()

        # With custom config
        install(
            config=LoggingConfig(log_response_body=True),
            processors=[MyCustomProcessor()],
        )
    """
    global _installed
    if _installed:
        return

    import structlog_httpx._instrumentor as _mod

    _mod._global_state = {
        "config": config or LoggingConfig(),
        "processors": _resolve_processors(processors, include_default_processors),
        "logger": logger or structlog.get_logger("structlog_httpx"),
    }

    wrapt.wrap_function_wrapper(
        "httpx", "HTTPTransport.handle_request", _global_sync_wrapper,
    )
    wrapt.wrap_function_wrapper(
        "httpx", "AsyncHTTPTransport.handle_async_request", _global_async_wrapper,
    )

    _installed = True


def uninstall() -> None:
    """Remove global httpx instrumentation.

    Restores the original ``handle_request`` / ``handle_async_request`` methods.
    """
    global _installed
    if not _installed:
        return

    import structlog_httpx._instrumentor as _mod

    # wrapt stores the original as __wrapped__
    try:
        original_sync = httpx.HTTPTransport.handle_request  # type: ignore[attr-defined]
        if hasattr(original_sync, "__wrapped__"):
            httpx.HTTPTransport.handle_request = original_sync.__wrapped__  # type: ignore[attr-defined]
    except AttributeError:
        pass

    try:
        original_async = httpx.AsyncHTTPTransport.handle_async_request  # type: ignore[attr-defined]
        if hasattr(original_async, "__wrapped__"):
            httpx.AsyncHTTPTransport.handle_async_request = original_async.__wrapped__  # type: ignore[attr-defined]
    except AttributeError:
        pass

    _mod._global_state = None
    _installed = False


def instrument_client(
    client: httpx.Client | httpx.AsyncClient,
    *,
    name: str | None = None,
    config: LoggingConfig | None = None,
    processors: list[BaseProcessor] | None = None,
    inherit_processors: bool = True,
    logger: Logger | None = None,
) -> None:
    """Instrument a specific httpx client with per-client settings.

    Wraps the client's transport with a logging transport. Per-client
    instrumentation takes priority over global instrumentation (the global
    wrapper skips already-instrumented transports).

    Args:
        client: The httpx Client or AsyncClient to instrument.
        name: A human-readable name that appears as ``client_name`` in logs.
        config: Per-client logging config. Falls back to ``LoggingConfig()`` defaults.
        processors: Per-client processors.
        inherit_processors: If True, global processors (from ``install()``) are
            prepended before per-client processors. If False, only per-client
            processors are used.
        logger: Custom logger for this client.

    Example::

        client = httpx.AsyncClient(base_url="https://api.binance.com")
        instrument_client(client, name="binance", config=LoggingConfig(log_response_body=True))
    """
    import structlog_httpx._instrumentor as _mod

    # Resolve processor chain
    if inherit_processors and _mod._global_state is not None:
        global_processors = list(_mod._global_state["processors"])
    else:
        global_processors = build_default_processors() if inherit_processors else []

    final_processors = global_processors + (processors or [])

    resolved_logger = logger
    if resolved_logger is None and _mod._global_state is not None:
        resolved_logger = _mod._global_state["logger"]
    if resolved_logger is None:
        resolved_logger = structlog.get_logger("structlog_httpx")

    if isinstance(client, httpx.AsyncClient):
        original = client._transport
        if isinstance(original, AsyncStructlogTransport):
            return  # Already instrumented
        client._transport = AsyncStructlogTransport(  # type: ignore[assignment]
            transport=original,  # type: ignore[arg-type]
            name=name,
            config=config or LoggingConfig(),
            processors=final_processors,
            logger=resolved_logger,
        )
    elif isinstance(client, httpx.Client):
        original = client._transport
        if isinstance(original, StructlogTransport):
            return
        client._transport = StructlogTransport(  # type: ignore[assignment]
            transport=original,  # type: ignore[arg-type]
            name=name,
            config=config or LoggingConfig(),
            processors=final_processors,
            logger=resolved_logger,
        )


def uninstrument_client(client: httpx.Client | httpx.AsyncClient) -> None:
    """Remove per-client instrumentation, restoring the original transport."""
    transport = client._transport
    if isinstance(transport, (StructlogTransport, AsyncStructlogTransport)):
        client._transport = transport._wrapped_transport  # type: ignore[assignment]

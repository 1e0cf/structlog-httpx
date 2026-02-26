import time
import typing
import structlog
import wrapt
import httpx
from structlog.stdlib import BoundLogger

# Type definitions
Logger = typing.Union[BoundLogger, typing.Any]
EventDict = typing.Dict[str, typing.Any]

DEFAULT_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-api-key",
}


class HttpxLoggingInstrumentor:
    def __init__(
        self,
        logger: typing.Optional[Logger] = None,
        log_request_body: bool = False,
        log_response_body: bool = False,
        max_body_size: int = 1024,
        sensitive_headers: typing.Optional[typing.Set[str]] = None,
    ):
        self.logger = logger or structlog.get_logger("httpx")
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_size = max_body_size
        self.sensitive_headers = sensitive_headers or DEFAULT_SENSITIVE_HEADERS
        # Normalize to lower case
        self.sensitive_headers = {h.lower() for h in self.sensitive_headers}

    def _redact_headers(self, headers: httpx.Headers) -> typing.Dict[str, str]:
        result = {}
        for k, v in headers.items():
            if k.lower() in self.sensitive_headers:
                result[k] = "***"
            else:
                result[k] = v
        return result

    def _truncate_body(self, body_bytes: bytes) -> typing.Union[str, bytes]:
        if len(body_bytes) > self.max_body_size:
            truncated = body_bytes[: self.max_body_size]
            return f"{truncated!r}... ({len(body_bytes)} bytes) [truncated]"
        try:
            return body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return body_bytes

    def _should_log_request_body(self, request: httpx.Request) -> bool:
        return self.log_request_body

    def _should_log_response_body(self, response: httpx.Response) -> bool:
        # If passed a callable, use it? For now simple boolean logic for V1
        return self.log_response_body

    def _extract_request_body(self, request: httpx.Request) -> typing.Any:
        # Only log if content is already available in memory to avoid breaking streams
        # or expensive reads during request phase
        if not self._should_log_request_body(request):
            return None

        # Accessing private attribute to check if stream is a byte stream (in-memory)
        # generic iterators are risky to consume.
        # httpx.Request.content property reads the stream.
        # If we want to be safe, we check if it has been read or is simple bytes.

        # Simplest safe approach: try to read .content only if we are sure it's safe?
        # Actually, reading request.read() consumes the generator if it is one.
        # For now, let's just log request.content if it exists (which it does for simple requests).
        try:
            # This might consume stream if it wasn't read?
            # httpx.Request(content=...) sets .stream to ByteStream which is safe to read multiple times.
            return self._truncate_body(request.content)
        except Exception:
            return "<stream>"

    def _extract_response_body(self, response: httpx.Response) -> typing.Any:
        if not self._should_log_response_body(response):
            return None

        # WARNING: This forces reading the response.
        try:
            # We need to be careful. In wrapper, we can call response.read() / aread()
            # But we must ensure we don't return a consumed response to user if they expected stream.
            # httpx.Response.read() caches content, so subsequent reads are fine.
            # The danger is only for very large files.
            # We assume if user enabled log_response_body, they accept this.

            # Since we are in the wrapper, we haven't returned the response yet.
            # For sync wrapper we can call read().
            # For async wrapper we need await aread().

            # Logic will be handled in wrapper specific methods.
            return None  # Placeholder, logic moved to wrapper
        except Exception:
            return "<error reading body>"

    def _log_request_start(
        self,
        method: str,
        url: str,
        headers: httpx.Headers,
        request: httpx.Request,
        is_error: bool = False,
    ):
        event_kw = {
            "method": method,
            "url": url,
        }

        # Only log headers and body on errors
        if is_error:
            event_kw["headers"] = self._redact_headers(headers)
            body = self._extract_request_body(request)
            if body:
                event_kw["request_body"] = body

        self.logger.debug("http_request_started", **event_kw)

    def _log_request_finished(
        self,
        method: str,
        url: str,
        status_code: int,
        duration: float,
        response: httpx.Response,
    ):
        event_kw = {
            "method": method,
            "url": url,
            "status_code": status_code,
            "duration": duration,
        }

        # Determine log level based on status
        level = "info"
        if status_code >= 400:
            level = "error"

        # Headers
        event_kw["response_headers"] = self._redact_headers(response.headers)

        self.logger.log(
            getattr(structlog.stdlib, level.upper(), structlog.stdlib.INFO),
            "http_request_finished",
            **event_kw,
        )

    def wrapper_sync(self, wrapped, instance, args, kwargs):
        # httpx.HTTPTransport.handle_request(request: Request)
        if len(args) > 0 and isinstance(args[0], httpx.Request):
            request = args[0]
        else:
            # Should not happen in recent httpx
            return wrapped(*args, **kwargs)

        method = request.method
        url = str(request.url)

        start_time = time.perf_counter()
        try:
            response = wrapped(*args, **kwargs)
        except Exception as exc:
            duration = time.perf_counter() - start_time
            self._log_request_start(
                method, url, request.headers, request, is_error=True
            )
            self.logger.error(
                "http_request_failed",
                method=method,
                url=url,
                duration=duration,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

        duration = time.perf_counter() - start_time

        is_error = response.status_code >= 400

        # Log request start with error context
        self._log_request_start(
            method, url, request.headers, request, is_error=is_error
        )

        # Prepare event kwargs
        event_kw = {
            "method": method,
            "url": url,
            "status_code": response.status_code,
            "duration": duration,
        }

        # Only log headers and body on errors
        if is_error:
            event_kw["response_headers"] = self._redact_headers(response.headers)

            # Handle Response Body only on errors
            if self._should_log_response_body(response):
                try:
                    response.read()  # Load into memory
                except httpx.ResponseNotRead:
                    pass

            response_body = None
            if self._should_log_response_body(response):
                try:
                    response_body = self._truncate_body(response.content)
                except httpx.ResponseNotRead:
                    pass  # Can't log body of streaming response

            if response_body:
                event_kw["response_body"] = response_body

        level = "error" if is_error else "info"
        getattr(self.logger, level)("http_request_finished", **event_kw)

        return response

    async def wrapper_async(self, wrapped, instance, args, kwargs):
        if len(args) > 0 and isinstance(args[0], httpx.Request):
            request = args[0]
        else:
            return await wrapped(*args, **kwargs)

        method = request.method
        url = str(request.url)

        start_time = time.perf_counter()
        try:
            response = await wrapped(*args, **kwargs)
        except Exception as exc:
            duration = time.perf_counter() - start_time
            self._log_request_start(
                method, url, request.headers, request, is_error=True
            )
            self.logger.error(
                "http_request_failed",
                method=method,
                url=url,
                duration=duration,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise

        duration = time.perf_counter() - start_time

        is_error = response.status_code >= 400

        # Log request start with error context
        self._log_request_start(
            method, url, request.headers, request, is_error=is_error
        )

        # Prepare event kwargs
        event_kw = {
            "method": method,
            "url": url,
            "status_code": response.status_code,
            "duration": duration,
        }

        # Only log headers and body on errors
        if is_error:
            event_kw["response_headers"] = self._redact_headers(response.headers)
            # Handle Response Body only on errors
            if self._should_log_response_body(response):
                try:
                    await response.aread()
                except httpx.ResponseNotRead:
                    pass

            response_body = None
            if self._should_log_response_body(response):
                try:
                    response_body = self._truncate_body(response.content)
                except httpx.ResponseNotRead:
                    pass  # Can't log body of streaming response

            if response_body:
                event_kw["response_body"] = response_body

        level = "error" if is_error else "info"
        getattr(self.logger, level)("http_request_finished", **event_kw)

        return response


_instrumentor = None


def install(
    logger: typing.Optional[Logger] = None,
    log_request_body: bool = False,
    log_response_body: bool = False,
    max_body_size: int = 1024,
    sensitive_headers: typing.Optional[typing.Set[str]] = None,
):
    """
    Globally instrument httpx to log requests using structlog.
    Patches httpx.HTTPTransport and httpx.AsyncHTTPTransport.
    """
    global _instrumentor
    if _instrumentor is not None:
        return  # Already installed

    _instrumentor = HttpxLoggingInstrumentor(
        logger=logger,
        log_request_body=log_request_body,
        log_response_body=log_response_body,
        max_body_size=max_body_size,
        sensitive_headers=sensitive_headers,
    )

    wrapt.wrap_function_wrapper(
        "httpx", "HTTPTransport.handle_request", _instrumentor.wrapper_sync
    )

    wrapt.wrap_function_wrapper(
        "httpx", "AsyncHTTPTransport.handle_async_request", _instrumentor.wrapper_async
    )

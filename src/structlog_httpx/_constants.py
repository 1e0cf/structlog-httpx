"""Default constants for structlog-httpx."""

DEFAULT_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-auth-token",
        "x-api-key",
    }
)

DEFAULT_LOGGABLE_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "application/json",
        "application/xml",
        "application/problem+json",
        "application/problem+xml",
        "text/plain",
        "text/xml",
    }
)

DEFAULT_MAX_BODY_SIZE: int = 1024

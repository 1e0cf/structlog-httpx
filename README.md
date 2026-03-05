# structlog-httpx

Structured logging for outgoing HTTPX requests using `structlog`.

## Features

- **Zero-config**: One `install()` call instruments all httpx clients globally.
- **Per-client control**: Name clients, override config and processors per client.
- **Processor pipeline**: Composable processors inspired by structlog's own design.
- **Smart defaults**: Sensitive header redaction, content-type body filtering, body truncation — all out of the box.
- **Async/sync**: Full support for both `httpx.Client` and `httpx.AsyncClient`.

## Installation

```bash
uv add structlog-httpx
```

## Quick Start

```python
from structlog_httpx import install

# That's it. All httpx requests are now logged.
install()
```

## Configuration

### LoggingConfig

Controls **what** data is collected:

```python
from structlog_httpx import install, LoggingConfig

install(
    config=LoggingConfig(
        log_request_body=True,
        log_response_body=True,
        log_request_headers=True,
        log_response_headers=True,
    ),
)
```

### Per-client instrumentation

```python
import httpx
from structlog_httpx import instrument_client, LoggingConfig

client = httpx.AsyncClient(base_url="https://api.example.com")
instrument_client(
    client,
    name="example",                                     # appears as client_name in logs
    config=LoggingConfig(log_response_body=True),        # override global config
)
```

### Transport wrapper (advanced)

```python
import httpx
from structlog_httpx import AsyncStructlogTransport, LoggingConfig

transport = AsyncStructlogTransport(
    transport=httpx.AsyncHTTPTransport(),
    name="example-gateway",
    config=LoggingConfig(log_request_body=True, log_response_body=True),
)
client = httpx.AsyncClient(transport=transport)
```

## Processors

Processors control **how** collected data is processed before logging. They run in order and can modify or suppress log events.

### Built-in processors (enabled by default)

- `RedactSensitiveHeaders` — replaces sensitive header values with `[REDACTED]`
- `FilterBodyByContentType` — removes response body for non-structured content types (HTML, images, etc.)
- `TruncateBodies` — truncates large bodies to prevent log bloat

### Custom processors

```python
from structlog_httpx import BaseProcessor, install

class DetectApiErrors(BaseProcessor):
    """Detect errors returned as 200 OK with error in JSON body."""

    def process(self, request, response, event):
        if response and response.status_code == 200:
            try:
                data = response.json()
                if "error" in data or data.get("success") is False:
                    event["level"] = "error"
                    event["api_error"] = data.get("error", data.get("message"))
            except Exception:
                pass
        return event

install(processors=[DetectApiErrors()])
```

### Processor composition

```python
from structlog_httpx import install, instrument_client, RedactSensitiveHeaders, TruncateBodies

# Global: default processors + custom
install(processors=[DetectApiErrors()])

# Per-client: inherits global processors + adds its own
instrument_client(client, name="binance", processors=[BinanceSpecificProcessor()])

# Per-client: only its own processors (no inheritance)
instrument_client(client, name="internal", processors=[MinimalProcessor()], inherit_processors=False)
```

### Configuring built-in processors

```python
from structlog_httpx import install, RedactSensitiveHeaders, FilterBodyByContentType, TruncateBodies

install(
    processors=[
        RedactSensitiveHeaders(sensitive={"authorization", "x-custom-secret"}),
        FilterBodyByContentType(allowed={"application/json"}),
        TruncateBodies(max_size=4096),
    ],
    include_default_processors=False,  # replace defaults entirely
)
```

## Uninstall

```python
from structlog_httpx import uninstall, uninstrument_client

# Remove global instrumentation
uninstall()

# Remove per-client instrumentation
uninstrument_client(client)
```

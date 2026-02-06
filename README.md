# structlog-httpx

Rich structured logging for HTTPX using `structlog` and `event_hooks`.

## Features

- **Non-invasive**: Uses standard `httpx` event hooks mechanism. No need to replace your `Client` class.
- **Rich Data**: Logs request URL, method, headers, response status, duration, and body (optional).
- **Hybrid Support**: Works with both synchronous `httpx.Client` and asynchronous `httpx.AsyncClient`.
- **Safe**: Doesn't break response streaming or affect performance by default.

## Installation

```bash
uv add structlog-httpx
```

## Usage

### Basic

```python
import httpx
from structlog_httpx import hooks

# Synchronous
client = httpx.Client(event_hooks=hooks)
client.get("https://example.com")

# Asynchronous
# import structlog_httpx
# client = httpx.AsyncClient(event_hooks=structlog_httpx.async_hooks)
```

### Advanced Configuration

You can configure what to log (headers, body):

```python
from structlog_httpx import StructLogHooks

# Enable headers and body logging
# NOTE: logging body forces reading the response into memory!
hooks_config = StructLogHooks(log_headers=True, log_body=True)

async with httpx.AsyncClient(event_hooks=hooks_config.async_hooks) as client:
    await client.get("https://example.com")
```

### Integration with `structlog-config`

This library plays perfectly with `structlog-config`. Since `structlog-config` silences the default `httpx` logger (to WARNING level), using `structlog-httpx` allows you to have full control over your HTTP logs without duplicate output.

See `examples/httpx_integration.py` in the root repository for a full example.

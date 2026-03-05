"""Tests for global install/uninstall and per-client instrumentation."""

from __future__ import annotations

import httpx
import pytest
import respx

import structlog_httpx
from structlog_httpx import (
    LoggingConfig,
    install,
    instrument_client,
    uninstall,
    uninstrument_client,
)
from structlog_httpx._instrumentor import AsyncStructlogTransport, StructlogTransport

from .conftest import LogCapture


# --- install / uninstall ---


class TestInstallUninstall:
    def test_install_sets_flag(self):
        install()
        assert structlog_httpx._installed is True

    def test_install_idempotent(self):
        install()
        install()  # should not raise
        assert structlog_httpx._installed is True

    def test_uninstall_clears_flag(self):
        install()
        uninstall()
        assert structlog_httpx._installed is False

    def test_uninstall_when_not_installed(self):
        uninstall()  # should not raise
        assert structlog_httpx._installed is False

    @respx.mock
    def test_sync_request_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        install(logger=log_capture)

        with httpx.Client() as client:
            resp = client.get("https://example.com/api")

        assert resp.status_code == 200
        assert len(log_capture.events) == 1
        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_finished"
        assert ev["_level"] == "info"
        assert ev["method"] == "GET"
        assert ev["status_code"] == 200
        assert "duration" in ev

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_request_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        install(logger=log_capture)

        async with httpx.AsyncClient() as client:
            resp = await client.get("https://example.com/api")

        assert resp.status_code == 200
        assert len(log_capture.events) == 1
        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_finished"
        assert ev["method"] == "GET"
        assert ev["status_code"] == 200

    @respx.mock
    def test_error_status_logged_as_error(self, log_capture: LogCapture):
        respx.get("https://example.com/fail").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        install(logger=log_capture)

        with httpx.Client() as client:
            resp = client.get("https://example.com/fail")

        assert resp.status_code == 500
        ev = log_capture.events[0]
        assert ev["_level"] == "error"
        assert ev["status_code"] == 500

    @respx.mock
    def test_4xx_logged_as_error(self, log_capture: LogCapture):
        respx.get("https://example.com/notfound").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        install(logger=log_capture)

        with httpx.Client() as client:
            client.get("https://example.com/notfound")

        ev = log_capture.events[0]
        assert ev["_level"] == "error"
        assert ev["status_code"] == 404

    @respx.mock
    def test_exception_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/timeout").mock(side_effect=httpx.ConnectError("timeout"))
        install(logger=log_capture)

        with pytest.raises(httpx.ConnectError):
            with httpx.Client() as client:
                client.get("https://example.com/timeout")

        assert len(log_capture.events) == 1
        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_failed"
        assert ev["_level"] == "error"
        assert ev["error_type"] == "ConnectError"

    @respx.mock
    @pytest.mark.asyncio
    async def test_async_exception_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/timeout").mock(side_effect=httpx.ConnectError("timeout"))
        install(logger=log_capture)

        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient() as client:
                await client.get("https://example.com/timeout")

        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_failed"
        assert ev["error_type"] == "ConnectError"

    @respx.mock
    def test_uninstall_stops_logging(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        install(logger=log_capture)
        uninstall()

        with httpx.Client() as client:
            client.get("https://example.com/api")

        assert len(log_capture.events) == 0


# --- LoggingConfig ---


class TestLoggingConfig:
    @respx.mock
    def test_response_body_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(
                200,
                json={"data": "value"},
                headers={"content-type": "application/json"},
            )
        )
        install(
            config=LoggingConfig(log_response_body=True),
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.get("https://example.com/api")

        ev = log_capture.events[0]
        assert "response_body" in ev

    @respx.mock
    def test_request_body_logged(self, log_capture: LogCapture):
        respx.post("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )
        install(
            config=LoggingConfig(log_request_body=True),
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.post("https://example.com/api", json={"key": "val"})

        ev = log_capture.events[0]
        assert "request_body" in ev
        assert "key" in ev["request_body"]

    @respx.mock
    def test_request_headers_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )
        install(
            config=LoggingConfig(log_request_headers=True),
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.get("https://example.com/api", headers={"x-custom": "hello"})

        ev = log_capture.events[0]
        assert "request_headers" in ev

    @respx.mock
    def test_response_headers_logged(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, headers={"x-server": "test"})
        )
        install(
            config=LoggingConfig(log_response_headers=True),
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.get("https://example.com/api")

        ev = log_capture.events[0]
        assert "response_headers" in ev

    @respx.mock
    def test_body_not_logged_when_disabled(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"data": "value"})
        )
        install(
            config=LoggingConfig(log_response_body=False, log_request_body=False),
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.get("https://example.com/api")

        ev = log_capture.events[0]
        assert "response_body" not in ev
        assert "request_body" not in ev


# --- instrument_client / uninstrument_client ---


class TestInstrumentClient:
    @respx.mock
    @pytest.mark.asyncio
    async def test_per_client_name(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        install(logger=log_capture)

        async with httpx.AsyncClient() as client:
            instrument_client(client, name="test-service", logger=log_capture)
            await client.get("https://example.com/api")

        # Per-client transport takes over, global wrapper skips it
        events_with_name = [e for e in log_capture.events if e.get("client_name") == "test-service"]
        assert len(events_with_name) == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_per_client_config_override(self, log_capture: LogCapture):
        respx.post("https://example.com/api").mock(
            return_value=httpx.Response(
                200,
                json={"result": "ok"},
                headers={"content-type": "application/json"},
            )
        )
        # Global: no body logging
        install(logger=log_capture)

        async with httpx.AsyncClient() as client:
            instrument_client(
                client,
                name="detailed",
                config=LoggingConfig(log_response_body=True),
                logger=log_capture,
            )
            await client.post("https://example.com/api", json={"q": "test"})

        events_with_name = [e for e in log_capture.events if e.get("client_name") == "detailed"]
        assert len(events_with_name) == 1
        assert "response_body" in events_with_name[0]

    @respx.mock
    def test_sync_instrument_client(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )

        with httpx.Client() as client:
            instrument_client(client, name="sync-svc", logger=log_capture)
            client.get("https://example.com/api")

        assert len(log_capture.events) == 1
        assert log_capture.events[0]["client_name"] == "sync-svc"

    @respx.mock
    def test_uninstrument_client_restores_transport(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )

        with httpx.Client() as client:
            original_transport = client._transport
            instrument_client(client, name="temp", logger=log_capture)
            assert isinstance(client._transport, StructlogTransport)

            uninstrument_client(client)
            assert client._transport is original_transport

            client.get("https://example.com/api")

        assert len(log_capture.events) == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_uninstrument_async_client(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )

        async with httpx.AsyncClient() as client:
            original = client._transport
            instrument_client(client, name="temp", logger=log_capture)
            assert isinstance(client._transport, AsyncStructlogTransport)

            uninstrument_client(client)
            assert client._transport is original

    def test_instrument_client_idempotent(self, log_capture: LogCapture):
        client = httpx.AsyncClient()
        instrument_client(client, name="svc", logger=log_capture)
        transport_after_first = client._transport
        instrument_client(client, name="svc", logger=log_capture)
        assert client._transport is transport_after_first

    @respx.mock
    @pytest.mark.asyncio
    async def test_per_client_skips_global_wrapper(self, log_capture: LogCapture):
        """Per-client instrumented client should not be double-logged by global wrapper."""
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )
        install(logger=log_capture)

        async with httpx.AsyncClient() as client:
            instrument_client(client, name="named", logger=log_capture)
            await client.get("https://example.com/api")

        # Should have exactly 1 event, not 2
        assert len(log_capture.events) == 1
        assert log_capture.events[0]["client_name"] == "named"


# --- Processor inheritance ---


class TestProcessorInheritance:
    @respx.mock
    @pytest.mark.asyncio
    async def test_inherit_processors_true(self, log_capture: LogCapture):
        """Per-client processors are appended after global ones."""
        from structlog_httpx import BaseProcessor

        call_order = []

        class GlobalProc(BaseProcessor):
            def process(self, request, response, event):
                call_order.append("global")
                return event

        class ClientProc(BaseProcessor):
            def process(self, request, response, event):
                call_order.append("client")
                return event

        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))

        install(
            processors=[GlobalProc()],
            include_default_processors=False,
            logger=log_capture,
        )

        async with httpx.AsyncClient() as client:
            instrument_client(
                client,
                name="test",
                processors=[ClientProc()],
                inherit_processors=True,
                logger=log_capture,
            )
            await client.get("https://example.com/api")

        assert "global" in call_order
        assert "client" in call_order
        assert call_order.index("global") < call_order.index("client")

    @respx.mock
    @pytest.mark.asyncio
    async def test_inherit_processors_false(self, log_capture: LogCapture):
        """Per-client processors replace global ones entirely."""
        from structlog_httpx import BaseProcessor

        call_order = []

        class GlobalProc(BaseProcessor):
            def process(self, request, response, event):
                call_order.append("global")
                return event

        class ClientProc(BaseProcessor):
            def process(self, request, response, event):
                call_order.append("client")
                return event

        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))

        install(
            processors=[GlobalProc()],
            include_default_processors=False,
            logger=log_capture,
        )

        async with httpx.AsyncClient() as client:
            instrument_client(
                client,
                name="test",
                processors=[ClientProc()],
                inherit_processors=False,
                logger=log_capture,
            )
            await client.get("https://example.com/api")

        assert "global" not in call_order
        assert "client" in call_order

    @respx.mock
    def test_processor_suppresses_event(self, log_capture: LogCapture):
        from structlog_httpx import BaseProcessor

        class SuppressHealth(BaseProcessor):
            def process(self, request, response, event):
                if "/health" in event.get("url", ""):
                    return None
                return event

        respx.get("https://example.com/health").mock(return_value=httpx.Response(200))
        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))

        install(
            processors=[SuppressHealth()],
            include_default_processors=False,
            logger=log_capture,
        )

        with httpx.Client() as client:
            client.get("https://example.com/health")
            client.get("https://example.com/api")

        assert len(log_capture.events) == 1
        assert "/api" in log_capture.events[0]["url"]

    @respx.mock
    def test_no_default_processors(self, log_capture: LogCapture):
        """include_default_processors=False should not add defaults."""
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200)
        )
        install(
            include_default_processors=False,
            logger=log_capture,
            config=LoggingConfig(log_request_headers=True),
        )

        with httpx.Client() as client:
            client.get(
                "https://example.com/api",
                headers={"authorization": "Bearer secret"},
            )

        ev = log_capture.events[0]
        # Without RedactSensitiveHeaders, authorization should be visible
        assert ev["request_headers"]["authorization"] == "Bearer secret"


# --- Content-length ---


class TestContentLength:
    @respx.mock
    def test_content_length_in_event(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(
                200,
                content=b"hello",
                headers={"content-length": "5"},
            )
        )
        install(logger=log_capture, include_default_processors=False)

        with httpx.Client() as client:
            client.get("https://example.com/api")

        ev = log_capture.events[0]
        assert ev["content_length"] == 5

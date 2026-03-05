"""Tests for direct transport wrapper usage."""

from __future__ import annotations

import httpx
import pytest
import respx

from structlog_httpx import (
    AsyncStructlogTransport,
    BaseProcessor,
    LoggingConfig,
    StructlogTransport,
)

from .conftest import LogCapture


class TestSyncTransport:
    @respx.mock
    def test_basic_request(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        transport = StructlogTransport(
            transport=httpx.HTTPTransport(),
            name="test-sync",
            logger=log_capture,
        )
        with httpx.Client(transport=transport) as client:
            resp = client.get("https://example.com/api")

        assert resp.status_code == 200
        assert len(log_capture.events) == 1
        ev = log_capture.events[0]
        assert ev["client_name"] == "test-sync"
        assert ev["method"] == "GET"
        assert ev["status_code"] == 200

    @respx.mock
    def test_with_config(self, log_capture: LogCapture):
        respx.post("https://example.com/api").mock(
            return_value=httpx.Response(
                200,
                json={"result": "ok"},
                headers={"content-type": "application/json"},
            )
        )
        transport = StructlogTransport(
            transport=httpx.HTTPTransport(),
            name="configured",
            config=LoggingConfig(log_request_body=True, log_response_body=True),
            logger=log_capture,
        )
        with httpx.Client(transport=transport) as client:
            client.post("https://example.com/api", json={"q": "test"})

        ev = log_capture.events[0]
        assert "request_body" in ev
        assert "response_body" in ev

    @respx.mock
    def test_with_custom_processors(self, log_capture: LogCapture):
        class TagProcessor(BaseProcessor):
            def process(self, request, response, event):
                event["tagged"] = True
                return event

        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))
        transport = StructlogTransport(
            transport=httpx.HTTPTransport(),
            processors=[TagProcessor()],
            logger=log_capture,
        )
        with httpx.Client(transport=transport) as client:
            client.get("https://example.com/api")

        assert log_capture.events[0]["tagged"] is True

    @respx.mock
    def test_exception_handling(self, log_capture: LogCapture):
        respx.get("https://example.com/fail").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        transport = StructlogTransport(
            transport=httpx.HTTPTransport(),
            name="fail-test",
            logger=log_capture,
        )
        with pytest.raises(httpx.ConnectError):
            with httpx.Client(transport=transport) as client:
                client.get("https://example.com/fail")

        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_failed"
        assert ev["client_name"] == "fail-test"
        assert ev["error_type"] == "ConnectError"

    @respx.mock
    def test_no_name(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))
        transport = StructlogTransport(
            transport=httpx.HTTPTransport(),
            logger=log_capture,
        )
        with httpx.Client(transport=transport) as client:
            client.get("https://example.com/api")

        ev = log_capture.events[0]
        assert "client_name" not in ev


class TestAsyncTransport:
    @respx.mock
    @pytest.mark.asyncio
    async def test_basic_request(self, log_capture: LogCapture):
        respx.get("https://example.com/api").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        transport = AsyncStructlogTransport(
            transport=httpx.AsyncHTTPTransport(),
            name="test-async",
            logger=log_capture,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get("https://example.com/api")

        assert resp.status_code == 200
        ev = log_capture.events[0]
        assert ev["client_name"] == "test-async"
        assert ev["method"] == "GET"

    @respx.mock
    @pytest.mark.asyncio
    async def test_with_config(self, log_capture: LogCapture):
        respx.post("https://example.com/api").mock(
            return_value=httpx.Response(
                200,
                json={"data": 123},
                headers={"content-type": "application/json"},
            )
        )
        transport = AsyncStructlogTransport(
            transport=httpx.AsyncHTTPTransport(),
            config=LoggingConfig(log_response_body=True),
            logger=log_capture,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://example.com/api", json={"key": "val"})

        ev = log_capture.events[0]
        assert "response_body" in ev

    @respx.mock
    @pytest.mark.asyncio
    async def test_exception_handling(self, log_capture: LogCapture):
        respx.get("https://example.com/fail").mock(
            side_effect=httpx.ConnectError("refused")
        )
        transport = AsyncStructlogTransport(
            transport=httpx.AsyncHTTPTransport(),
            name="async-fail",
            logger=log_capture,
        )
        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient(transport=transport) as client:
                await client.get("https://example.com/fail")

        ev = log_capture.events[0]
        assert ev["_event"] == "http_request_failed"
        assert ev["client_name"] == "async-fail"

    @respx.mock
    @pytest.mark.asyncio
    async def test_processor_suppresses(self, log_capture: LogCapture):
        class SuppressAll(BaseProcessor):
            def process(self, request, response, event):
                return None

        respx.get("https://example.com/api").mock(return_value=httpx.Response(200))
        transport = AsyncStructlogTransport(
            transport=httpx.AsyncHTTPTransport(),
            processors=[SuppressAll()],
            logger=log_capture,
        )
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get("https://example.com/api")

        assert len(log_capture.events) == 0

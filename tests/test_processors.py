"""Tests for built-in processors."""

from __future__ import annotations

import httpx
import pytest

from structlog_httpx import (
    BaseProcessor,
    FilterBodyByContentType,
    RedactSensitiveHeaders,
    TruncateBodies,
)
from structlog_httpx._types import HttpxLogEvent


def _make_request(url: str = "https://example.com", method: str = "GET") -> httpx.Request:
    return httpx.Request(method, url)


def _make_response(
    status_code: int = 200,
    content_type: str = "application/json",
    content: bytes = b'{"ok": true}',
) -> httpx.Response:
    resp = httpx.Response(
        status_code,
        headers={"content-type": content_type},
        content=content,
    )
    return resp


# --- RedactSensitiveHeaders ---


class TestRedactSensitiveHeaders:
    def test_redacts_default_headers(self):
        proc = RedactSensitiveHeaders()
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "request_headers": {
                "authorization": "Bearer secret123",
                "content-type": "application/json",
                "x-api-key": "key123",
            },
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result is not None
        assert result["request_headers"]["authorization"] == "[REDACTED]"
        assert result["request_headers"]["x-api-key"] == "[REDACTED]"
        assert result["request_headers"]["content-type"] == "application/json"

    def test_redacts_response_headers(self):
        proc = RedactSensitiveHeaders()
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_headers": {
                "set-cookie": "session=abc",
                "content-type": "text/plain",
            },
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["response_headers"]["set-cookie"] == "[REDACTED]"
        assert result["response_headers"]["content-type"] == "text/plain"

    def test_custom_sensitive_headers(self):
        proc = RedactSensitiveHeaders(sensitive={"x-custom-secret"})
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "request_headers": {
                "authorization": "Bearer visible",
                "x-custom-secret": "hidden",
            },
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["request_headers"]["authorization"] == "Bearer visible"
        assert result["request_headers"]["x-custom-secret"] == "[REDACTED]"

    def test_custom_replacement(self):
        proc = RedactSensitiveHeaders(replacement="***")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "request_headers": {"authorization": "Bearer token"},
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["request_headers"]["authorization"] == "***"

    def test_case_insensitive(self):
        proc = RedactSensitiveHeaders(sensitive={"Authorization"})
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "request_headers": {"authorization": "Bearer token"},
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["request_headers"]["authorization"] == "[REDACTED]"

    def test_no_headers_in_event(self):
        proc = RedactSensitiveHeaders()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com"}
        result = proc.process(_make_request(), _make_response(), event)
        assert result is not None
        assert "request_headers" not in result


# --- FilterBodyByContentType ---


class TestFilterBodyByContentType:
    def test_keeps_json_body(self):
        proc = FilterBodyByContentType()
        resp = _make_response(content_type="application/json")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": '{"ok": true}',
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" in result

    def test_removes_html_body(self):
        proc = FilterBodyByContentType()
        resp = _make_response(content_type="text/html; charset=utf-8", content=b"<html></html>")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "<html></html>",
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" not in result

    def test_removes_image_body(self):
        proc = FilterBodyByContentType()
        resp = _make_response(content_type="image/png", content=b"\x89PNG")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "\\x89PNG",
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" not in result

    def test_keeps_xml_body(self):
        proc = FilterBodyByContentType()
        resp = _make_response(content_type="application/xml")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "<root/>",
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" in result

    def test_keeps_text_html_when_custom_allowed(self):
        proc = FilterBodyByContentType(allowed={"text/html"})
        resp = _make_response(content_type="text/html")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "<html></html>",
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" in result

    def test_no_body_in_event(self):
        proc = FilterBodyByContentType()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com"}
        result = proc.process(_make_request(), _make_response(), event)
        assert result is not None

    def test_no_response(self):
        proc = FilterBodyByContentType()
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "data",
        }
        result = proc.process(_make_request(), None, event)
        assert "response_body" in result

    def test_content_type_with_charset(self):
        proc = FilterBodyByContentType()
        resp = _make_response(content_type="application/json; charset=utf-8")
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "{}",
        }
        result = proc.process(_make_request(), resp, event)
        assert "response_body" in result


# --- TruncateBodies ---


class TestTruncateBodies:
    def test_truncates_long_body(self):
        proc = TruncateBodies(max_size=10)
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "a" * 100,
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["response_body"].startswith("aaaaaaaaaa...")
        assert "[truncated]" in result["response_body"]

    def test_keeps_short_body(self):
        proc = TruncateBodies(max_size=100)
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "short",
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["response_body"] == "short"

    def test_truncates_request_body(self):
        proc = TruncateBodies(max_size=5)
        event: HttpxLogEvent = {
            "method": "POST",
            "url": "https://example.com",
            "request_body": "long request body",
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["request_body"].startswith("long ...")
        assert "[truncated]" in result["request_body"]

    def test_no_body_in_event(self):
        proc = TruncateBodies()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com"}
        result = proc.process(_make_request(), _make_response(), event)
        assert result is not None

    def test_default_max_size(self):
        proc = TruncateBodies()
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "x" * 1024,
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert result["response_body"] == "x" * 1024  # exactly at limit, not truncated

    def test_one_over_limit(self):
        proc = TruncateBodies()
        event: HttpxLogEvent = {
            "method": "GET",
            "url": "https://example.com",
            "response_body": "x" * 1025,
        }
        result = proc.process(_make_request(), _make_response(), event)
        assert "[truncated]" in result["response_body"]


# --- Processor chain ---


class TestProcessorChain:
    def test_processor_returning_none_suppresses(self):
        class SuppressAll(BaseProcessor):
            def process(self, request, response, event):
                return None

        proc = SuppressAll()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com"}
        assert proc.process(_make_request(), _make_response(), event) is None

    def test_custom_processor_adds_field(self):
        class AddField(BaseProcessor):
            def process(self, request, response, event):
                event["custom"] = "value"
                return event

        proc = AddField()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com"}
        result = proc.process(_make_request(), _make_response(), event)
        assert result["custom"] == "value"

    def test_custom_processor_changes_level(self):
        class AlwaysError(BaseProcessor):
            def process(self, request, response, event):
                event["level"] = "error"
                return event

        proc = AlwaysError()
        event: HttpxLogEvent = {"method": "GET", "url": "https://example.com", "level": "info"}
        result = proc.process(_make_request(), _make_response(), event)
        assert result["level"] == "error"

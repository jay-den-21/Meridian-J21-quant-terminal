from __future__ import annotations

from eodhd_codegen_app.server import (
    is_allowed_local_host,
    is_allowed_local_origin,
    is_json_content_type,
    local_base_url_from_host,
)


def test_json_content_type_allows_only_json_posts() -> None:
    assert is_json_content_type("application/json")
    assert is_json_content_type("application/json; charset=utf-8")
    assert not is_json_content_type("text/plain")
    assert not is_json_content_type("application/x-www-form-urlencoded")


def test_side_effect_host_guard_allows_only_loopback_hosts() -> None:
    assert is_allowed_local_host("127.0.0.1:8000")
    assert is_allowed_local_host("localhost:8000")
    assert is_allowed_local_host("[::1]:8000")
    assert not is_allowed_local_host("example.com")
    assert not is_allowed_local_host("127.0.0.1.evil.test")


def test_side_effect_origin_guard_allows_only_loopback_http_origins() -> None:
    assert is_allowed_local_origin("http://127.0.0.1:8000")
    assert is_allowed_local_origin("http://localhost:8000")
    assert is_allowed_local_origin("http://[::1]:8000")
    assert not is_allowed_local_origin("https://example.com")
    assert not is_allowed_local_origin("http://127.0.0.1.evil.test")


def test_local_base_url_uses_current_loopback_port() -> None:
    assert local_base_url_from_host("127.0.0.1:54321") == "http://127.0.0.1:54321"
    assert local_base_url_from_host("localhost:49152") == "http://localhost:49152"
    assert local_base_url_from_host("[::1]:60000") == "http://[::1]:60000"
    assert local_base_url_from_host("example.com:8000") == "http://127.0.0.1:8000"

from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from io import BytesIO
from subprocess import CompletedProcess
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from eodhd_codegen_app.client import EodhdHttpClient
from eodhd_codegen_app.execution_export import ExecutionExportStore
from eodhd_codegen_app.server import CodegenRequestHandler
from eodhd_codegen_app.token_store import TokenStore


def test_local_http_generate_execute_export_and_missing_token(tmp_path, monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    provider_calls = []

    class Response(BytesIO):
        status = 200

    def provider_transport(request, **kwargs):
        provider_calls.append(request.full_url)
        return Response(json.dumps([{"date": "2024-01-02", "close": 100}]).encode())

    class Handler(CodegenRequestHandler):
        token_store = TokenStore(
            fallback_path=tmp_path / "token",
            runner=lambda *args, **kwargs: CompletedProcess(args, 44, "", ""),
        )
        client = EodhdHttpClient(transport=provider_transport)
        export_store = ExecutionExportStore()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    payload = {
        "endpoint": "historical_eod", "symbols": "AAPL.US",
        "date_from": "2024-01-02", "date_to": "2024-01-02",
    }

    def post(path, body):
        request = Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Origin": base},
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    try:
        with urlopen(base, timeout=5) as response:
            assert response.status == 200
            assert "<html" in response.read().decode().lower()
        with urlopen(base + "/api/endpoints", timeout=5) as response:
            assert json.load(response)["endpoints"]
        generated = post("/api/generate", payload)
        assert "YOUR_EODHD_API_KEY" in json.dumps(generated)
        with pytest.raises(HTTPError) as error:
            post("/api/execute", payload)
        assert error.value.code == 502
        assert "not set" in error.value.read().decode()
        assert provider_calls == []

        Handler.token_store.set_stored_token("synthetic-local-test-only")
        executed = post("/api/execute", payload)
        assert len(provider_calls) == 1
        assert "synthetic-local-test-only" not in json.dumps(executed)
        export_id = executed["result"]["export_id"]
        with urlopen(base + f"/api/exports/{export_id}.csv", timeout=5) as response:
            assert response.headers["Content-Type"].startswith("text/csv")
            csv = response.read().decode("utf-8-sig")
            assert "2024-01-02" in csv
            assert "100" in csv
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()

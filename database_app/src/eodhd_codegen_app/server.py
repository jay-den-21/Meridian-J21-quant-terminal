from __future__ import annotations

import json
import os
import re
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import urlparse

from eodhd_codegen_app.client import MAX_EXECUTION_HTTP_REQUESTS, EodhdExecutionError, EodhdHttpClient
from eodhd_codegen_app.codegen import build_urls, generate_snippets
from eodhd_codegen_app.cost import estimate_api_cost
from eodhd_codegen_app.endpoints import endpoint_payload, inventory_payload
from eodhd_codegen_app.execution_export import ExecutionExportStore, csv_bytes, export_filename
from eodhd_codegen_app.instrument_catalog import (
    ExchangeDirectoryCache,
    catalog_menu_payload,
    load_eodhd_exchange_directory,
)
from eodhd_codegen_app.request_model import ValidationError, validate_payload
from eodhd_codegen_app.token_store import TokenStore, TokenStoreError
from eodhd_codegen_app.universe import load_universe, menu_payload, resolve_universe_symbols


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
JSON_CONTENT_TYPES = {"application/json", "application/json; charset=utf-8"}
EXPORT_PATH_RE = re.compile(r"^/api/exports/([A-Za-z0-9_-]{20,80})\.csv$")


class CodegenRequestHandler(BaseHTTPRequestHandler):
    client = EodhdHttpClient()
    token_store = TokenStore()
    catalog_cache = ExchangeDirectoryCache()
    export_store = ExecutionExportStore()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" or path == "/index.html":
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if path == "/static/styles.css":
            self._send_static("styles.css", "text/css; charset=utf-8")
            return
        if path == "/static/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
            return
        if path == "/static/timezone.js":
            self._send_static("timezone.js", "application/javascript; charset=utf-8")
            return
        if path == "/static/instrument_catalog.js":
            self._send_static("instrument_catalog.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/endpoints":
            self._send_json({"endpoints": endpoint_payload(), "inventory_only": inventory_payload()})
            return
        if path == "/api/config":
            self._handle_config_status()
            return
        if path == "/api/universe/menu":
            self._send_json(menu_payload())
            return
        if path == "/api/instrument-catalog/menu":
            self._send_json(catalog_menu_payload(cache=self.catalog_cache))
            return
        export_match = EXPORT_PATH_RE.fullmatch(path)
        if export_match:
            if self._guard_local_read_request():
                self._handle_export(export_match.group(1))
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if not self._guard_side_effect_request(require_json=True):
            return
        path = urlparse(self.path).path
        if path == "/api/generate":
            self._handle_generate()
            return
        if path == "/api/execute":
            self._handle_execute()
            return
        if path == "/api/config/token":
            self._handle_config_set_token()
            return
        if path == "/api/universe/load":
            self._handle_universe_load()
            return
        if path == "/api/universe/resolve":
            self._handle_universe_resolve()
            return
        if path == "/api/instrument-catalog/exchanges":
            self._handle_instrument_catalog_exchanges()
            return
        self._send_json({"error": "not found"}, status=404)

    def do_DELETE(self) -> None:
        if not self._guard_side_effect_request(require_json=False):
            return
        if urlparse(self.path).path == "/api/config/token":
            self._handle_config_delete_token()
            return
        self._send_json({"error": "not found"}, status=404)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and not is_allowed_local_origin(origin):
            self._send_json({"error": "origin is not allowed"}, status=403)
            return
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle_generate(self) -> None:
        try:
            api_request = validate_payload(self._read_json())
            self._send_json(
                {
                    "request": api_request.as_public_dict(),
                    "snippets": generate_snippets(api_request, app_base_url=self._local_base_url()),
                    "cost": estimate_api_cost(api_request).as_dict(),
                }
            )
        except ValidationError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _handle_execute(self) -> None:
        try:
            payload = self._read_json()
            api_request = validate_payload(payload)
            cost = estimate_api_cost(api_request)
            request_count = len(build_urls(api_request))
            if request_count > MAX_EXECUTION_HTTP_REQUESTS:
                self._send_json(
                    {
                        "error": (
                            f"Execute API is capped at {MAX_EXECUTION_HTTP_REQUESTS} HTTP requests; "
                            f"this request would make {request_count}. Use generated code for larger lists."
                        ),
                        "cost": cost.as_dict(),
                    },
                    status=400,
                )
                return
            if cost.requires_confirmation and not payload.get("confirm_cost", False):
                self._send_json(
                    {
                        "error": "bulk request requires confirm_cost=true",
                        "cost": cost.as_dict(),
                    },
                    status=400,
                )
                return
            api_key = self.token_store.resolve_token()
            result = self.client.execute(api_request, api_key=api_key)
            export_snapshot = self.export_store.replace(api_request, result.rows)
            self._send_json(
                {
                    "request": api_request.as_public_dict(),
                    "cost": cost.as_dict(),
                    "result": result.as_dict(export_id=export_snapshot.export_id),
                }
            )
        except ValidationError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except (EodhdExecutionError, TokenStoreError) as exc:
            self._send_json({"error": str(exc)}, status=502)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _handle_instrument_catalog_exchanges(self) -> None:
        try:
            self._read_json()
            result = load_eodhd_exchange_directory(
                api_key=self.token_store.resolve_token(),
                client=self.client,
                cache=self.catalog_cache,
            )
            self._send_json(result)
        except (EodhdExecutionError, TokenStoreError) as exc:
            self._send_json({"error": str(exc)}, status=502)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _handle_export(self, export_id: str) -> None:
        snapshot = self.export_store.get(export_id)
        if snapshot is None:
            self._send_json({"error": "export is unavailable or no longer current"}, status=404)
            return
        self._send_bytes(
            csv_bytes(snapshot),
            content_type="text/csv; charset=utf-8",
            filename=export_filename(snapshot),
        )

    def _handle_config_status(self) -> None:
        try:
            self._send_json({"token": self.token_store.status().as_dict()})
        except TokenStoreError as exc:
            self._send_json(
                {
                    "token": {
                        "configured": bool(os.environ.get("EODHD_API_KEY")),
                        "source": "environment" if os.environ.get("EODHD_API_KEY") else "none",
                        "can_delete": False,
                        "message": str(exc),
                    }
                },
                status=200,
            )

    def _handle_config_set_token(self) -> None:
        try:
            payload = self._read_json()
            token = payload.get("token", "")
            if not isinstance(token, str):
                raise ValidationError("token must be text")
            status = self.token_store.set_stored_token(token)
            self._send_json({"token": status.as_dict()})
        except (ValidationError, TokenStoreError) as exc:
            self._send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _handle_config_delete_token(self) -> None:
        try:
            status = self.token_store.delete_stored_token()
            self._send_json({"token": status.as_dict()})
        except TokenStoreError as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_universe_load(self) -> None:
        try:
            payload = self._read_json()
            result = load_universe(payload)
            self._send_json(result)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _handle_universe_resolve(self) -> None:
        try:
            payload = self._read_json()
            result = resolve_universe_symbols(payload)
            self._send_json(result)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except json.JSONDecodeError:
            self._send_json({"error": "request body must be JSON"}, status=400)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body or "{}")
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")
        return payload

    def _guard_side_effect_request(self, *, require_json: bool) -> bool:
        host = self.headers.get("Host", "")
        if not is_allowed_local_host(host):
            self._send_json({"error": "host is not allowed"}, status=403)
            return False

        origin = self.headers.get("Origin", "")
        if origin and not is_allowed_local_origin(origin):
            self._send_json({"error": "origin is not allowed"}, status=403)
            return False

        if require_json and not is_json_content_type(self.headers.get("Content-Type", "")):
            self._send_json({"error": "Content-Type must be application/json"}, status=415)
            return False

        return True

    def _guard_local_read_request(self) -> bool:
        host = self.headers.get("Host", "")
        if not is_allowed_local_host(host):
            self._send_json({"error": "host is not allowed"}, status=403)
            return False
        origin = self.headers.get("Origin", "")
        if origin and not is_allowed_local_origin(origin):
            self._send_json({"error": "origin is not allowed"}, status=403)
            return False
        return True

    def _send_static(self, filename: str, content_type: str) -> None:
        static_file = files("eodhd_codegen_app").joinpath("static", filename)
        body = static_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, *, content_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _local_base_url(self) -> str:
        return local_base_url_from_host(self.headers.get("Host", ""))


def run_server(*, host: str = "127.0.0.1", port: int = 8000, open_browser: bool = False) -> None:
    httpd = ThreadingHTTPServer((host, port), CodegenRequestHandler)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"EODHD code generator app running at {url}")
    if open_browser:
        webbrowser.open(url)
    httpd.serve_forever()


def is_json_content_type(value: str) -> bool:
    return value.split(";")[0].strip().lower() == "application/json"


def is_allowed_local_host(value: str) -> bool:
    hostname = _hostname_from_header(value)
    return hostname in LOCAL_HOSTS


def is_allowed_local_origin(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS


def local_base_url_from_host(value: str) -> str:
    hostname = _hostname_from_header(value)
    if hostname not in LOCAL_HOSTS:
        return "http://127.0.0.1:8000"
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    port = _port_from_header(value)
    return f"http://{host}:{port}" if port else f"http://{host}"


def _hostname_from_header(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text.startswith("["):
        end = text.find("]")
        return text[1:end] if end != -1 else text
    return text.rsplit(":", 1)[0].lower()


def _port_from_header(value: str) -> str:
    text = value.strip()
    if text.startswith("["):
        end = text.find("]")
        if end != -1 and text[end + 1 : end + 2] == ":":
            port = text[end + 2 :]
            return port if port.isdecimal() else ""
        return ""
    if ":" not in text:
        return ""
    port = text.rsplit(":", 1)[1]
    return port if port.isdecimal() else ""

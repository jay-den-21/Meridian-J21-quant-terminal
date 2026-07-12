from __future__ import annotations

import json
from datetime import timedelta
from pprint import pformat
from textwrap import indent
from urllib.parse import quote, urlencode

from eodhd_codegen_app.endpoints import BASE_URL, LIVE_OHLCV_SYMBOLS_PER_REQUEST
from eodhd_codegen_app.request_model import ApiRequest


PUBLIC_TOKEN_PLACEHOLDER = "YOUR_EODHD_API_KEY"


def build_urls(request: ApiRequest, *, api_token: str = PUBLIC_TOKEN_PLACEHOLDER) -> list[str]:
    """Build EODHD URLs for a validated request.

    Input: normalized `ApiRequest` and token placeholder or real token.
    Output: one or more endpoint URLs.
    Flow: endpoint id -> path + query params -> encoded URL list.
    """
    values = request.values

    if request.endpoint == "historical_eod":
        return [
            _url(
                f"/eod/{_path_part(symbol)}",
                {
                    "from": _date_param(values.get("date_from")),
                    "to": _date_param(values.get("date_to")),
                    "period": values["period"],
                    "order": values["order"],
                    "api_token": api_token,
                    "fmt": request.fmt,
                },
            )
            for symbol in request.symbols
        ]

    if request.endpoint == "intraday":
        return [
            _url(
                f"/intraday/{_path_part(symbol)}",
                {
                    "interval": values["interval"],
                    "from": values.get("from_timestamp"),
                    "to": values.get("to_timestamp"),
                    "split-dt": "1" if values.get("split_datetime") else None,
                    "api_token": api_token,
                    "fmt": request.fmt,
                },
            )
            for symbol in request.symbols
        ]

    if request.endpoint == "live_ohlcv":
        urls = []
        for symbols in _chunks(request.symbols, LIVE_OHLCV_SYMBOLS_PER_REQUEST):
            first_symbol = symbols[0]
            rest = symbols[1:]
            urls.append(
                _url(
                    f"/real-time/{_path_part(first_symbol)}",
                    {
                        "s": ",".join(rest) if rest else None,
                        "api_token": api_token,
                        "fmt": request.fmt,
                    },
                )
            )
        return urls

    if request.endpoint == "bulk_last_day_eod":
        dates = _bulk_dates(values)
        return [
            _url(
                f"/eod-bulk-last-day/{_path_part(request.exchange)}",
                {
                    "date": _date_param(bulk_date),
                    "symbols": ",".join(request.symbols) if request.symbols else None,
                    "api_token": api_token,
                    "fmt": request.fmt,
                },
            )
            for bulk_date in dates
        ]

    if request.endpoint == "dividends":
        return _symbol_series_urls(request, "/div", api_token=api_token)

    if request.endpoint == "splits":
        return _symbol_series_urls(request, "/splits", api_token=api_token)

    if request.endpoint == "technical":
        urls = []
        for symbol in request.symbols:
            urls.append(
                _url(
                    f"/technical/{_path_part(symbol)}",
                    {
                        "from": _date_param(values.get("date_from")),
                        "to": _date_param(values.get("date_to")),
                        "order": values["order"],
                        "function": values["function"],
                        "period": values.get("indicator_period"),
                        "filter": values.get("filter"),
                        "splitadjusted_only": "1" if values.get("splitadjusted_only") else None,
                        "api_token": api_token,
                        "fmt": request.fmt,
                    },
                )
            )
        return urls

    if request.endpoint == "screener":
        return [
            _url(
                "/screener",
                {
                    "sort": values.get("sort"),
                    "filters": values.get("filters"),
                    "signals": values.get("signal"),
                    "limit": values.get("limit"),
                    "offset": values.get("offset"),
                    "api_token": api_token,
                    "fmt": request.fmt,
                },
            )
        ]

    if request.endpoint == "exchange_symbol_list":
        params = {
            "api_token": api_token,
            "fmt": request.fmt,
            "delisted": "1" if values.get("delisted") else None,
        }
        if values.get("type_filter") != "all":
            params["type"] = values["type_filter"]
        return [_url(f"/exchange-symbol-list/{_path_part(request.exchange)}", params)]

    if request.endpoint == "instrument_search":
        params = {
            "api_token": api_token,
            "fmt": "json",
            "limit": values.get("limit"),
        }
        if request.exchange:
            params["exchange"] = request.exchange
        if values.get("type_filter") != "all":
            params["type"] = values["type_filter"]
        return [_url(f"/search/{_path_part(values['search_query'])}", params)]

    if request.endpoint == "exchanges_list":
        return [_url("/exchanges-list/", {"api_token": api_token, "fmt": "json"})]

    if request.endpoint == "exchange_details":
        return [_url(f"/v2/exchange-details/{_path_part(request.exchange)}", {"api_token": api_token, "fmt": "json"})]

    if request.endpoint == "symbol_change_history":
        return [
            _url(
                "/symbol-change-history",
                {
                    "from": _date_param(values.get("date_from")),
                    "to": _date_param(values.get("date_to")),
                    "api_token": api_token,
                    "fmt": request.fmt,
                },
            )
        ]

    if request.endpoint == "id_mapping":
        return [
            _url(
                "/id-mapping",
                {
                    f"filter[{values['filter_name']}]": values["filter_value"],
                    "page[limit]": values.get("limit"),
                    "page[offset]": values.get("offset"),
                    "api_token": api_token,
                    "fmt": "json",
                },
            )
        ]

    raise ValueError(f"unsupported endpoint: {request.endpoint}")


def generate_snippets(request: ApiRequest, *, app_base_url: str = "http://127.0.0.1:8000") -> dict[str, object]:
    """Generate direct URLs and language snippets without leaking a real API token."""
    public_urls = build_urls(request, api_token=PUBLIC_TOKEN_PLACEHOLDER)
    template_urls = build_urls(request, api_token="{api_token}")
    curl_urls = build_urls(request, api_token="${EODHD_API_KEY}")

    return {
        "direct_urls": public_urls,
        "python_requests": _python_requests(template_urls, fmt=request.fmt),
        "python_symbol_loop": _python_symbol_loop(request),
        "curl": _curl(curl_urls),
        "javascript_fetch": _javascript_fetch(template_urls, fmt=request.fmt),
        "javascript_symbol_loop": _javascript_symbol_loop(request),
        "local_proxy_python": _local_proxy_python(request, app_base_url=app_base_url),
    }


def _symbol_series_urls(request: ApiRequest, prefix: str, *, api_token: str) -> list[str]:
    values = request.values
    return [
        _url(
            f"{prefix}/{_path_part(symbol)}",
            {
                "from": _date_param(values.get("date_from")),
                "to": _date_param(values.get("date_to")),
                "api_token": api_token,
                "fmt": request.fmt,
            },
        )
        for symbol in request.symbols
    ]


def _python_requests(template_urls: list[str], *, fmt: str) -> str:
    urls_json = indent(json.dumps(template_urls, indent=4), "    ").strip()
    if fmt == "csv":
        return f"""import csv
import os
from io import StringIO

import requests

api_token = os.environ["EODHD_API_KEY"]
urls = {urls_json}

for url_template in urls:
    url = url_template.format(api_token=api_token)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    rows = list(csv.DictReader(StringIO(response.text)))
    print(rows)
"""

    return f"""import os
import requests

api_token = os.environ["EODHD_API_KEY"]
urls = {urls_json}

for url_template in urls:
    url = url_template.format(api_token=api_token)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    print(response.json())
"""


def _python_symbol_loop(request: ApiRequest) -> str:
    if request.endpoint == "bulk_last_day_eod":
        return _python_bulk_loop(request)
    if request.endpoint == "live_ohlcv":
        return _python_live_loop(request)
    if not _loop_path_template(request) or not request.symbols:
        return _python_requests(build_urls(request, api_token="{api_token}"), fmt=request.fmt)

    symbols_json = indent(json.dumps(list(request.symbols), indent=4), "    ").strip()
    params = _clean_loop_params(_public_loop_params(request))
    params_json = indent(json.dumps(params, indent=4), "    ").strip()
    url_template = f"{BASE_URL}{_loop_path_template(request)}"
    return f"""import os
import requests

api_token = os.environ["EODHD_API_KEY"]
symbols = {symbols_json}
base_params = {params_json}
url_template = "{url_template}"

for symbol in symbols:
    params = {{**base_params, "api_token": api_token, "fmt": "{request.fmt}"}}
    url = url_template.format(symbol=symbol, exchange="{request.exchange}")
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    print(symbol, response.text if "{request.fmt}" == "csv" else response.json())
"""


def _python_bulk_loop(request: ApiRequest) -> str:
    symbols_json = indent(json.dumps(list(request.symbols), indent=4), "    ").strip()
    dates_json = indent(json.dumps(_bulk_date_strings(request), indent=4), "    ").strip()
    return f"""import os
import requests

api_token = os.environ["EODHD_API_KEY"]
exchange = "{request.exchange}"
symbols = {symbols_json}
dates = {dates_json}
url = "{BASE_URL}/eod-bulk-last-day/{{exchange}}"

for trade_date in dates:
    params = {{"api_token": api_token, "fmt": "{request.fmt}"}}
    if trade_date:
        params["date"] = trade_date
    if symbols:
        params["symbols"] = ",".join(symbols)
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    print(trade_date or "latest", response.text if "{request.fmt}" == "csv" else response.json())
"""


def _python_live_loop(request: ApiRequest) -> str:
    symbols_json = indent(json.dumps(list(request.symbols), indent=4), "    ").strip()
    return f"""import os
import requests

api_token = os.environ["EODHD_API_KEY"]
symbols = {symbols_json}
chunk_size = {LIVE_OHLCV_SYMBOLS_PER_REQUEST}

for start in range(0, len(symbols), chunk_size):
    chunk = symbols[start:start + chunk_size]
    first_symbol = chunk[0]
    rest = chunk[1:]
    params = {{"api_token": api_token, "fmt": "{request.fmt}"}}
    if rest:
        params["s"] = ",".join(rest)
    response = requests.get(f"{BASE_URL}/real-time/{{first_symbol}}", params=params, timeout=30)
    response.raise_for_status()
    print(first_symbol, response.text if "{request.fmt}" == "csv" else response.json())
"""


def _curl(urls: list[str]) -> str:
    exports = "export EODHD_API_KEY=your_api_key_here"
    commands = [f'curl --fail --location "{url}"' for url in urls]
    return "\n".join([exports, *commands])


def _javascript_fetch(template_urls: list[str], *, fmt: str) -> str:
    urls_json = indent(json.dumps(template_urls, indent=4), "    ").strip()
    if fmt == "csv":
        return f"""const apiToken = process.env.EODHD_API_KEY;
const urls = {urls_json};

for (const urlTemplate of urls) {{
  const url = urlTemplate.replace("{{api_token}}", encodeURIComponent(apiToken));
  const response = await fetch(url);
  if (!response.ok) {{
    throw new Error(`EODHD request failed: ${{response.status}} ${{await response.text()}}`);
  }}
  console.log(await response.text());
}}
"""

    return f"""const apiToken = process.env.EODHD_API_KEY;
const urls = {urls_json};

for (const urlTemplate of urls) {{
  const url = urlTemplate.replace("{{api_token}}", encodeURIComponent(apiToken));
  const response = await fetch(url);
  if (!response.ok) {{
    throw new Error(`EODHD request failed: ${{response.status}} ${{await response.text()}}`);
  }}
  console.log(await response.json());
}}
"""


def _javascript_symbol_loop(request: ApiRequest) -> str:
    if request.endpoint == "bulk_last_day_eod":
        return _javascript_bulk_loop(request)
    if request.endpoint == "live_ohlcv":
        return _javascript_live_loop(request)
    if not _loop_path_template(request) or not request.symbols:
        return _javascript_fetch(build_urls(request, api_token="{api_token}"), fmt=request.fmt)

    symbols_json = indent(json.dumps(list(request.symbols), indent=2), "  ").strip()
    params_json = indent(json.dumps(_clean_loop_params(_public_loop_params(request)), indent=2), "  ").strip()
    url_template = f"{BASE_URL}{_loop_path_template(request)}"
    return f"""const apiToken = process.env.EODHD_API_KEY;
const symbols = {symbols_json};
const baseParams = {params_json};
const urlTemplate = "{url_template}";

for (const symbol of symbols) {{
  const params = new URLSearchParams({{ ...baseParams, api_token: apiToken, fmt: "{request.fmt}" }});
  const path = urlTemplate.replace("{{symbol}}", symbol).replace("{{exchange}}", "{request.exchange}");
  const response = await fetch(`${{path}}?${{params}}`);
  if (!response.ok) {{
    throw new Error(`EODHD request failed: ${{response.status}} ${{await response.text()}}`);
  }}
  console.log(symbol, "{request.fmt}" === "csv" ? await response.text() : await response.json());
}}
"""


def _javascript_bulk_loop(request: ApiRequest) -> str:
    symbols_json = indent(json.dumps(list(request.symbols), indent=2), "  ").strip()
    dates_json = indent(json.dumps(_bulk_date_strings(request), indent=2), "  ").strip()
    return f"""const apiToken = process.env.EODHD_API_KEY;
const exchange = "{request.exchange}";
const symbols = {symbols_json};
const dates = {dates_json};
const url = "{BASE_URL}/eod-bulk-last-day/" + encodeURIComponent(exchange);

for (const tradeDate of dates) {{
  const params = new URLSearchParams({{ api_token: apiToken, fmt: "{request.fmt}" }});
  if (tradeDate) {{
    params.set("date", tradeDate);
  }}
  if (symbols.length) {{
    params.set("symbols", symbols.join(","));
  }}
  const response = await fetch(`${{url}}?${{params}}`);
  if (!response.ok) {{
    throw new Error(`EODHD request failed: ${{response.status}} ${{await response.text()}}`);
  }}
  console.log(tradeDate || "latest", "{request.fmt}" === "csv" ? await response.text() : await response.json());
}}
"""


def _javascript_live_loop(request: ApiRequest) -> str:
    symbols_json = indent(json.dumps(list(request.symbols), indent=2), "  ").strip()
    return f"""const apiToken = process.env.EODHD_API_KEY;
const symbols = {symbols_json};
const chunkSize = {LIVE_OHLCV_SYMBOLS_PER_REQUEST};

for (let start = 0; start < symbols.length; start += chunkSize) {{
  const chunk = symbols.slice(start, start + chunkSize);
  const firstSymbol = chunk[0];
  const rest = chunk.slice(1);
  const params = new URLSearchParams({{ api_token: apiToken, fmt: "{request.fmt}" }});
  if (rest.length) {{
    params.set("s", rest.join(","));
  }}
  const response = await fetch(`{BASE_URL}/real-time/${{encodeURIComponent(firstSymbol)}}?${{params}}`);
  if (!response.ok) {{
    throw new Error(`EODHD request failed: ${{response.status}} ${{await response.text()}}`);
  }}
  console.log(firstSymbol, "{request.fmt}" === "csv" ? await response.text() : await response.json());
}}
"""


def _local_proxy_python(request: ApiRequest, *, app_base_url: str) -> str:
    payload = {
        "endpoint": request.endpoint,
        "asset": request.asset,
        "fmt": request.fmt,
        "preview_limit": request.preview_limit,
        "params": request.as_public_dict()["params"],
    }
    payload_python = indent(pformat(payload, sort_dicts=False, width=100), "    ").strip()
    base_url_json = json.dumps(app_base_url)
    return f"""import requests

# Uses the token saved in this local app's Login / Config.
# Keep the local EODHD Code Generator app running at app_base_url.
app_base_url = {base_url_json}
payload = {payload_python}

check = requests.post(f"{{app_base_url}}/api/generate", json=payload, timeout=30)
check.raise_for_status()
cost = check.json().get("cost", {{}})
if cost.get("requires_confirmation"):
    print(cost)
    answer = input("Type EXECUTE to run this request through the local app: ")
    if answer != "EXECUTE":
        raise SystemExit("cancelled")
    payload["confirm_cost"] = True

response = requests.post(f"{{app_base_url}}/api/execute", json=payload, timeout=60)
if not response.ok:
    print(response.text)
response.raise_for_status()
print(response.json())
"""


def _url(path: str, params: dict[str, object]) -> str:
    clean_params = {
        key: str(value)
        for key, value in params.items()
        if value is not None and str(value) != ""
    }
    query = urlencode(clean_params, safe=",$.[]:><=")
    query = query.replace("api_token=%7Bapi_token%7D", "api_token={api_token}")
    query = query.replace("api_token=%24%7BEODHD_API_KEY%7D", "api_token=${EODHD_API_KEY}")
    query = query.replace("api_token=$%7BEODHD_API_KEY%7D", "api_token=${EODHD_API_KEY}")
    return f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"


def _path_part(value: str) -> str:
    return quote(value, safe="._-")


def _date_param(value: object) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _bulk_dates(values: dict[str, object]) -> list[object]:
    if values.get("date_from") is not None and values.get("date_to") is not None:
        current = values["date_from"]
        end = values["date_to"]
        dates = []
        while current <= end:
            dates.append(current)
            current = current + timedelta(days=1)
        return dates
    return [values.get("trade_date")]


def _bulk_date_strings(request: ApiRequest) -> list[str | None]:
    return [_date_param(value) for value in _bulk_dates(request.values)]


def _chunks(symbols: tuple[str, ...], size: int) -> list[tuple[str, ...]]:
    return [symbols[index : index + size] for index in range(0, len(symbols), size)]


def _loop_path_template(request: ApiRequest) -> str:
    if request.endpoint == "historical_eod":
        return "/eod/{symbol}"
    if request.endpoint == "intraday":
        return "/intraday/{symbol}"
    if request.endpoint == "live_ohlcv":
        return "/real-time/{symbol}"
    if request.endpoint == "bulk_last_day_eod":
        return "/eod-bulk-last-day/{exchange}"
    if request.endpoint == "dividends":
        return "/div/{symbol}"
    if request.endpoint == "splits":
        return "/splits/{symbol}"
    if request.endpoint == "technical":
        return "/technical/{symbol}"
    return ""


def _public_loop_params(request: ApiRequest) -> dict[str, object]:
    values = request.values
    if request.endpoint == "historical_eod":
        return {
            "from": _date_param(values.get("date_from")),
            "to": _date_param(values.get("date_to")),
            "period": values["period"],
            "order": values["order"],
        }
    if request.endpoint == "intraday":
        return {
            "interval": values["interval"],
            "from": values.get("from_timestamp"),
            "to": values.get("to_timestamp"),
            "split-dt": "1" if values.get("split_datetime") else None,
        }
    if request.endpoint == "live_ohlcv":
        return {}
    if request.endpoint == "bulk_last_day_eod":
        return {"symbols": ",".join(request.symbols) if request.symbols else None}
    if request.endpoint in {"dividends", "splits"}:
        return {
            "from": _date_param(values.get("date_from")),
            "to": _date_param(values.get("date_to")),
        }
    if request.endpoint == "technical":
        return {
            "from": _date_param(values.get("date_from")),
            "to": _date_param(values.get("date_to")),
            "order": values["order"],
            "function": values["function"],
            "period": values.get("indicator_period"),
            "filter": values.get("filter"),
            "splitadjusted_only": "1" if values.get("splitadjusted_only") else None,
        }
    return {}


def _clean_loop_params(params: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in params.items() if value is not None and str(value) != ""}

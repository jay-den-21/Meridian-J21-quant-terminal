"""Endpoint-local scope planning and parameter validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import product

from fdp_cn.tushare.errors import (
    TushareCapabilityError,
    TushareDataError,
    TushareParameterError,
)
from fdp_cn.tushare.models import (
    EndpointPlanRequest,
    EndpointSpec,
    EndpointUnit,
    ParameterSpec,
    RequestScalar,
)


RESERVED_PARAMETERS = frozenset(
    {"api_name", "fields", "limit", "offset", "schema", "table", "token"}
)
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_endpoint_params(
    spec: EndpointSpec,
    params: Mapping[str, object] | None,
) -> dict[str, RequestScalar]:
    """Validate only catalog-declared caller parameters; never pass unknowns through."""
    supplied = params or {}
    normalized_names: dict[str, str] = {}
    for raw_name in supplied:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise TushareParameterError(
                "Tushare parameter names must be non-empty text"
            )
        name = raw_name.strip()
        folded = name.casefold()
        if folded in RESERVED_PARAMETERS:
            raise TushareParameterError(f"Tushare parameter {name} is reserved")
        if folded in normalized_names:
            raise TushareParameterError(f"Duplicate Tushare parameter: {name}")
        normalized_names[folded] = raw_name

    allowed = {name.casefold(): name for name in spec.request_params}
    unknown = sorted(
        raw_name.strip()
        for folded, raw_name in normalized_names.items()
        if folded not in allowed
    )
    if unknown:
        raise TushareParameterError(
            f"Unsupported parameter(s) for {spec.key}: {', '.join(unknown)}"
        )

    result: dict[str, RequestScalar] = {}
    for folded, raw_name in normalized_names.items():
        canonical_name = allowed[folded]
        definition = spec.request_params[canonical_name]
        result[canonical_name] = _normalize_parameter(
            canonical_name,
            supplied[raw_name],
            definition,
        )
    missing = sorted(
        name
        for name, definition in spec.request_params.items()
        if definition.required and name not in result
    )
    if missing:
        raise TushareParameterError(
            f"Missing required parameter(s) for {spec.key}: {', '.join(missing)}"
        )
    return result


def plan_endpoint_units(
    spec: EndpointSpec,
    request: EndpointPlanRequest | None = None,
) -> tuple[EndpointUnit, ...]:
    """Plan broad scopes; page offsets are advanced later within each returned unit."""
    if not spec.executable:
        reason = spec.capability.reason or "endpoint is disabled"
        raise TushareCapabilityError(
            f"Tushare endpoint {spec.key} is not executable: {reason}"
        )
    if spec.page_limit is None:
        raise TushareCapabilityError(
            f"Tushare endpoint {spec.key} has no executable page limit"
        )
    plan = request or EndpointPlanRequest()
    params = validate_endpoint_params(spec, plan.params)
    _merge_structured_dates(
        params, spec=spec, date_from=plan.date_from, date_to=plan.date_to
    )
    codes = _normalize_codes(plan.codes)
    parameter_codes = _take_parameter_codes(params)
    if codes and parameter_codes:
        raise TushareParameterError("Use either codes or param ts_code, not both")
    codes = codes or parameter_codes
    _merge_codes(params, spec=spec, codes=codes)
    _validate_date_scope(params)

    base: dict[str, RequestScalar] = dict(spec.fixed_params)
    overlap = set(base) & set(params)
    if overlap:
        raise TushareParameterError(
            f"Caller parameters conflict with fixed {spec.key} parameters: {', '.join(sorted(overlap))}"
        )
    base.update(params)

    if spec.scope_kind == "code_date_range":
        scope_codes = _take_parameter_codes(base)
        if not scope_codes:
            raise TushareParameterError(
                f"Tushare endpoint {spec.key} requires at least one ts_code"
            )
        scopes = [{**base, "ts_code": code} for code in scope_codes]
    else:
        scopes = [base]

    for fanout in spec.fanouts:
        expanded: list[dict[str, RequestScalar]] = []
        for scope, value in product(scopes, fanout.values):
            overlap = ({fanout.parameter} | set(fanout.fixed_params)) & set(scope)
            if overlap:
                raise TushareParameterError(
                    f"Endpoint fanout conflicts with scope parameter(s): {', '.join(sorted(overlap))}"
                )
            expanded.append(
                {
                    **scope,
                    **fanout.fixed_params,
                    fanout.parameter: value,
                }
            )
        scopes = expanded

    return tuple(
        EndpointUnit(
            endpoint_key=spec.key,
            scope_key=_scope_key(scope),
            params=scope,
            page_limit=spec.page_limit,
        )
        for scope in scopes
    )


def next_page_offset(
    spec: EndpointSpec,
    *,
    current_offset: int,
    rows_returned: int,
) -> int | None:
    """Advance by the documented limit only after a full page."""
    if current_offset < 0:
        raise ValueError("current_offset must be non-negative")
    if rows_returned < 0:
        raise ValueError("rows_returned must be non-negative")
    if spec.page_limit is None:
        return None
    if rows_returned > spec.page_limit:
        raise TushareDataError(
            f"Tushare endpoint {spec.key} returned more than its requested page limit"
        )
    if spec.pagination.kind == "offset_limit_probe":
        return current_offset + rows_returned if rows_returned else None
    if rows_returned < spec.page_limit:
        return None
    return current_offset + spec.page_limit


def _normalize_parameter(
    name: str, value: object, definition: ParameterSpec
) -> RequestScalar:
    if definition.kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise TushareParameterError(
                f"Tushare parameter {name} must be non-empty text"
            )
        return value.strip()
    if definition.kind == "date":
        return _normalize_date(value, name=name)
    if definition.kind == "integer":
        if isinstance(value, bool):
            raise TushareParameterError(f"Tushare parameter {name} must be an integer")
        try:
            normalized = int(value)  # type: ignore[arg-type]
            exact = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise TushareParameterError(
                f"Tushare parameter {name} must be an integer"
            ) from error
        if not exact.is_finite() or exact != normalized:
            raise TushareParameterError(f"Tushare parameter {name} must be an integer")
        return normalized
    if definition.kind == "decimal":
        if isinstance(value, bool):
            raise TushareParameterError(f"Tushare parameter {name} must be decimal")
        try:
            normalized_decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise TushareParameterError(
                f"Tushare parameter {name} must be decimal"
            ) from error
        if not normalized_decimal.is_finite():
            raise TushareParameterError(f"Tushare parameter {name} must be finite")
        return normalized_decimal
    if definition.kind == "choice":
        if not isinstance(value, str) or value not in definition.choices:
            choices = ", ".join(definition.choices)
            raise TushareParameterError(
                f"Tushare parameter {name} must be one of: {choices}"
            )
        return value
    raise AssertionError(f"unknown Tushare parameter kind: {definition.kind}")


def _normalize_date(value: object, *, name: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if not isinstance(value, str) or not value.strip():
        raise TushareParameterError(f"Tushare parameter {name} must be a date")
    raw = value.strip()
    formats = ("%Y%m%d", "%Y-%m-%d")
    for format_string in formats:
        try:
            return datetime.strptime(raw, format_string).strftime("%Y%m%d")
        except ValueError:
            continue
    raise TushareParameterError(
        f"Tushare parameter {name} must be YYYYMMDD or YYYY-MM-DD"
    )


def _merge_structured_dates(
    params: dict[str, RequestScalar],
    *,
    spec: EndpointSpec,
    date_from: date | str | None,
    date_to: date | str | None,
) -> None:
    if date_from is None and date_to is None:
        return
    if date_from is None or date_to is None:
        raise TushareParameterError("date_from and date_to must be supplied together")
    if "start_date" not in spec.request_params or "end_date" not in spec.request_params:
        raise TushareParameterError(
            f"Tushare endpoint {spec.key} does not accept a date range"
        )
    if "start_date" in params or "end_date" in params or "trade_date" in params:
        raise TushareParameterError("Use structured dates or date params, not both")
    params["start_date"] = _normalize_date(date_from, name="date_from")
    params["end_date"] = _normalize_date(date_to, name="date_to")


def _normalize_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TushareParameterError("Tushare codes must be text")
        for raw_code in value.split(","):
            code = raw_code.strip().upper()
            if not code or not _CODE.fullmatch(code):
                raise TushareParameterError(f"Invalid Tushare code: {raw_code}")
            if code not in seen:
                seen.add(code)
                result.append(code)
    return tuple(result)


def _take_parameter_codes(params: dict[str, RequestScalar]) -> tuple[str, ...]:
    value = params.pop("ts_code", None)
    if value is None:
        return ()
    if not isinstance(value, str):
        raise TushareParameterError("Tushare parameter ts_code must be text")
    return _normalize_codes((value,))


def _merge_codes(
    params: dict[str, RequestScalar],
    *,
    spec: EndpointSpec,
    codes: tuple[str, ...],
) -> None:
    if not codes:
        return
    if "ts_code" not in spec.request_params:
        raise TushareParameterError(
            f"Tushare endpoint {spec.key} does not accept codes"
        )
    params["ts_code"] = ",".join(codes)


def _validate_date_scope(params: Mapping[str, RequestScalar]) -> None:
    if "trade_date" in params and ({"start_date", "end_date"} & set(params)):
        raise TushareParameterError(
            "trade_date cannot be combined with start_date/end_date"
        )
    start = params.get("start_date")
    end = params.get("end_date")
    if isinstance(start, str) and isinstance(end, str) and start > end:
        raise TushareParameterError("Tushare start_date must not be after end_date")


def _scope_key(params: Mapping[str, RequestScalar]) -> str:
    if not params:
        return "all"
    visible = ",".join(f"{name}={params[name]}" for name in sorted(params))
    return visible[:240]

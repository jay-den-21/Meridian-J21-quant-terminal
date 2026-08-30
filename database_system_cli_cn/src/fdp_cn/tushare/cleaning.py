"""Strict endpoint-local normalization for validated Tushare pages."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from fdp_cn.tushare.errors import TushareCapabilityError, TushareDataError
from fdp_cn.tushare.models import CleanedPage, ColumnKind, EndpointSpec, TushareResponse


def clean_page(spec: EndpointSpec, response: TushareResponse) -> CleanedPage:
    """Normalize one page, collapse exact duplicates, and reject key conflicts."""
    if not spec.executable:
        raise TushareCapabilityError(f"Tushare endpoint {spec.key} is not executable")
    if response.endpoint_key != spec.key or response.api_name != spec.api_name:
        raise TushareDataError("Tushare response does not match its endpoint contract")
    if not response.items and not response.fields:
        return CleanedPage(endpoint_key=spec.key, fetched_rows=0, rows=())

    normalized_fields = _normalize_fields(spec, response.fields)
    expected = set(spec.fields)
    actual = set(normalized_fields)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise TushareDataError(
            f"Tushare fields do not match {spec.key}: {' '.join(details)}"
        )

    by_key: dict[tuple[object, ...], MappingProxyType[str, object]] = {}
    order: list[tuple[object, ...]] = []
    for row_number, item in enumerate(response.items):
        raw_row = dict(zip(normalized_fields, item, strict=True))
        row = {
            name: _normalize_value(
                raw_row[name],
                kind=spec.column_types[name],
                field=name,
                row_number=row_number,
            )
            for name in spec.fields
        }
        for name in spec.fields:
            if row[name] is None and name not in spec.nullable_columns:
                raise TushareDataError(
                    f"Tushare field {name} is null in {spec.key} row {row_number}"
                )
            if (
                spec.column_types[name] == "text"
                and row[name] == ""
                and name not in spec.nullable_columns
            ):
                raise TushareDataError(
                    f"Tushare field {name} is empty in {spec.key} row {row_number}"
                )
        _validate_business_values(spec, row, row_number=row_number)
        business_key = tuple(row[name] for name in spec.business_key)
        if any(value is None or value == "" for value in business_key):
            raise TushareDataError(
                f"Tushare business key is empty in {spec.key} row {row_number}"
            )
        frozen_row = MappingProxyType(row)
        existing = by_key.get(business_key)
        if existing is None:
            by_key[business_key] = frozen_row
            order.append(business_key)
        elif dict(existing) != row:
            raise TushareDataError(
                f"Conflicting rows share a business key in {spec.key} row {row_number}"
            )

    return CleanedPage(
        endpoint_key=spec.key,
        fetched_rows=len(response.items),
        rows=tuple(by_key[key] for key in order),
    )


def _normalize_fields(spec: EndpointSpec, fields: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: dict[str, str] = {}
    for source_name in fields:
        target_name = spec.field_aliases.get(source_name, source_name)
        if target_name not in spec.fields:
            raise TushareDataError(
                f"Unknown Tushare field for {spec.key}: {source_name}"
            )
        previous = seen.get(target_name)
        if previous is not None:
            raise TushareDataError(
                f"Tushare alias collision for {spec.key}: {previous} and {source_name}"
            )
        seen[target_name] = source_name
        result.append(target_name)
    return tuple(result)


def _normalize_value(
    value: object,
    *,
    kind: ColumnKind,
    field: str,
    row_number: int,
) -> object:
    if value is None:
        return None
    if kind == "text":
        if isinstance(value, bool):
            raise _type_error(field, row_number, "text")
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            if not Decimal(str(value)).is_finite():
                raise _type_error(field, row_number, "finite text")
            return format(value, "g")
        raise _type_error(field, row_number, "text")
    if kind == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            for format_string in ("%Y%m%d", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value.strip(), format_string).date()
                except ValueError:
                    continue
        raise _type_error(field, row_number, "YYYYMMDD date")
    if kind == "decimal":
        if isinstance(value, bool):
            raise _type_error(field, row_number, "decimal")
        try:
            normalized = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, AttributeError) as error:
            raise _type_error(field, row_number, "decimal") from error
        if not normalized.is_finite():
            raise _type_error(field, row_number, "finite decimal")
        return normalized
    if kind == "integer":
        if isinstance(value, bool):
            raise _type_error(field, row_number, "integer")
        try:
            normalized_integer = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as error:
            raise _type_error(field, row_number, "integer") from error
        try:
            if Decimal(str(value)) != normalized_integer:
                raise _type_error(field, row_number, "integer")
        except InvalidOperation as error:
            raise _type_error(field, row_number, "integer") from error
        return normalized_integer
    raise AssertionError(f"unknown Tushare column kind: {kind}")


def _type_error(field: str, row_number: int, expected: str) -> TushareDataError:
    return TushareDataError(
        f"Tushare field {field} in row {row_number} must be {expected}"
    )


def _validate_business_values(
    spec: EndpointSpec,
    row: dict[str, object],
    *,
    row_number: int,
) -> None:
    """Reject sparse or internally impossible rows before they can overwrite good data."""

    api_name = spec.api_name
    if api_name == "trade_cal" and row["is_open"] not in {"0", "1"}:
        raise TushareDataError(
            f"Tushare field is_open is invalid in {spec.key} row {row_number}"
        )
    if api_name not in {"daily", "sw_daily", "cyq_chips"}:
        return

    nonnegative_fields = (
        ("price", "percent")
        if api_name == "cyq_chips"
        else ("open", "high", "low", "close", "vol", "amount")
    )
    if api_name == "sw_daily":
        nonnegative_fields = (*nonnegative_fields, "float_mv", "total_mv")
    for field in nonnegative_fields:
        value = row[field]
        if value is not None and (not isinstance(value, Decimal) or value < 0):
            raise TushareDataError(
                f"Tushare field {field} is negative in {spec.key} row {row_number}"
            )

    if api_name in {"daily", "sw_daily"}:
        open_price = row["open"]
        high = row["high"]
        low = row["low"]
        close = row["close"]
        # The official SW history contains both partial quote rows and retained
        # source anomalies (for example an open above high). Preserve those
        # values verbatim instead of silently rewriting or dropping the page.
        if api_name == "sw_daily":
            return
        if not all(
            isinstance(value, Decimal) for value in (open_price, high, low, close)
        ):
            raise TushareDataError(
                f"Tushare OHLC values are incomplete in {spec.key} row {row_number}"
            )
        if high < max(open_price, low, close) or low > min(open_price, high, close):
            raise TushareDataError(
                f"Tushare OHLC values are inconsistent in {spec.key} row {row_number}"
            )

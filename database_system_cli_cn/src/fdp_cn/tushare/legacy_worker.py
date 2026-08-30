"""Child-process entrypoint for one preserved legacy getter."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys


PRODUCT_ROOT = Path(__file__).resolve().parents[3]
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

from fdp_cn.tushare.catalog import get_endpoint_spec  # noqa: E402


_PROTECTED_PARAMS = frozenset(
    {
        "db_engine",
        "table_name",
        "table_name_cn",
        "ts",
        "ts_api",
        "ts_pro",
        "write_db",
    }
)

_LEGACY_RUNNER_FUNCTIONS = {
    "fin.fin_balancesheet": "get_fin_balancesheet_run",
    "fin.fin_balancesheet_vip": "get_fin_balancesheet_vip_run",
    "fin.fin_cashflow": "get_fin_cashflow_run",
    "fin.fin_cashflow_vip": "get_fin_cashflow_vip_run",
    "fin.fin_income": "get_fin_income_run",
    "fin.fin_income_all_vip": "get_fin_income_all_vip_run",
    "hk.hk_ccass_hold_detail": "get_hk_ccass_hold_detail_run",
}


def run_endpoint(
    endpoint: str,
    *,
    date_from: str,
    date_to: str,
    codes: tuple[str, ...] = (),
    params: dict[str, object] | None = None,
) -> None:
    spec = get_endpoint_spec(endpoint)
    _assert_legacy_database_target()
    module_name, separator, class_name = spec.legacy_id.rpartition(".")
    if not separator:
        raise ValueError(f"invalid legacy endpoint id: {spec.legacy_id}")
    module = importlib.import_module(module_name)
    runtime_params = _params(str_date=date_from, end_date=date_to)
    runner_name = _LEGACY_RUNNER_FUNCTIONS.get(spec.key)
    if runner_name is not None:
        if codes:
            runtime_params.codelist = list(codes)
            if len(codes) == 1:
                runtime_params.code = codes[0]
        _apply_extra_params(runtime_params, params)
        getattr(module, runner_name)(runtime_params)
        return

    endpoint_class = getattr(module, class_name)
    instance = endpoint_class(runtime_params)
    if codes:
        instance.params.codelist = list(codes)
        if len(codes) == 1:
            instance.params.code = codes[0]
    _apply_extra_params(instance.params, params)
    instance.run()


def _assert_legacy_database_target() -> None:
    database = _configured_database_name()
    if database != "a_share":
        raise RuntimeError(
            "legacy compatibility execution requires config db=a_share; "
            f"configured database is {database!r}"
        )


def _configured_database_name() -> str:
    from basis.constant import ts2db_config

    db_config = ts2db_config.ts2db_config.get("db_config", {})
    if not isinstance(db_config, dict):
        return ""
    return str(db_config.get("db", "")).strip()


def _params(*args: object, **kwargs: object) -> object:
    from basis import _params as params_factory

    return params_factory(*args, **kwargs)


def _apply_extra_params(target: object, params: dict[str, object] | None) -> None:
    for name, value in (params or {}).items():
        if name in _PROTECTED_PARAMS or not name.isidentifier():
            raise ValueError(f"legacy parameter is not allowed: {name}")
        setattr(target, name, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--from", dest="date_from", required=True)
    parser.add_argument("--to", dest="date_to", required=True)
    parser.add_argument("--codes", default="")
    parser.add_argument("--params-json", default="{}")
    args = parser.parse_args(argv)
    raw_params = json.loads(args.params_json)
    if not isinstance(raw_params, dict):
        raise ValueError("params-json must be an object")
    run_endpoint(
        args.endpoint,
        date_from=args.date_from,
        date_to=args.date_to,
        codes=tuple(value.strip() for value in args.codes.split(",") if value.strip()),
        params=raw_params,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

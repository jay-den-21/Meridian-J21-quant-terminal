from datetime import date
import inspect

from fdp.get_data.historical.get_index_daily import get_index_daily
from fdp.get_data.historical.get_market_calendar import get_market_calendar
from fdp.get_data.historical.get_etf_daily import get_etf_daily
from fdp.get_data.historical.get_stk_daily import get_stk_daily
from fdp.sources.eodhd.ingest import DEFAULT_INDEX_PROVIDER_SYMBOLS


def test_historical_get_data_scripts_are_importable() -> None:
    assert callable(get_stk_daily)
    assert callable(get_etf_daily)
    assert callable(get_index_daily)
    assert callable(get_market_calendar)
    assert DEFAULT_INDEX_PROVIDER_SYMBOLS


def test_historical_get_data_function_annotations_keep_date_range_contract() -> None:
    annotations = get_stk_daily.__annotations__

    assert annotations["date_from"] is date
    assert annotations["date_to"] is date


def test_historical_get_data_wrappers_can_opt_into_inactive_symbols() -> None:
    stock_signature = inspect.signature(get_stk_daily)
    etf_signature = inspect.signature(get_etf_daily)

    assert stock_signature.parameters["include_inactive"].default is False
    assert etf_signature.parameters["include_inactive"].default is False

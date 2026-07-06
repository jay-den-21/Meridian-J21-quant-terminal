from fdp.storage import (
    SYSTEM_SCHEMA,
    US_SHARE_SCHEMA,
    data_quality_issue,
    etf_daily_price,
    etf_instrument,
    index_daily_price,
    index_instrument,
    instrument,
    instrument_identifier_history,
    instrument_lifecycle_event,
    market_calendar,
    metadata,
    quarantine_plan,
    quarantined_daily_price_row,
    stock_daily_price,
    stock_instrument,
)


def test_initial_metadata_contains_project_tables() -> None:
    assert f"{US_SHARE_SCHEMA}.instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.stock_instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.etf_instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.index_instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.instrument_identifier_history" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.instrument_lifecycle_event" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.stock_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.etf_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.index_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.market_calendar" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.data_quality_issue" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.repair_plan" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.quarantine_plan" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.quarantined_daily_price_row" in metadata.tables


def test_instrument_keeps_standard_and_provider_symbols() -> None:
    assert instrument.schema == US_SHARE_SCHEMA
    assert "symbol" in instrument.c
    assert "provider_symbol" in instrument.c
    assert {"provider", "provider_symbol"} in [
        set(constraint.columns.keys()) for constraint in instrument.constraints
    ]


def test_asset_daily_price_tables_have_instrument_date_uniqueness() -> None:
    for price_table in (stock_daily_price, etf_daily_price, index_daily_price):
        assert "symbol" in price_table.c
        assert "provider_symbol" in price_table.c
        assert {"instrument_id", "trade_date"} in [
            set(constraint.columns.keys()) for constraint in price_table.constraints
        ]


def test_asset_instrument_views_are_read_handles() -> None:
    for view in (stock_instrument, etf_instrument, index_instrument):
        assert view.schema == US_SHARE_SCHEMA
        assert view.info["is_view"] is True
        assert "instrument_id" in view.c
        assert "provider_symbol" in view.c


def test_identifier_history_supports_symbol_and_provider_symbol_history() -> None:
    expected_columns = {
        "identifier_history_id",
        "instrument_id",
        "id_type",
        "id_value",
        "valid_from",
        "valid_to",
        "source",
        "created_at",
        "updated_at",
    }
    assert expected_columns.issubset(instrument_identifier_history.c.keys())
    assert {"instrument_id", "id_type", "id_value", "valid_from", "source"} in [
        set(constraint.columns.keys()) for constraint in instrument_identifier_history.constraints
    ]


def test_lifecycle_event_records_instrument_state_changes() -> None:
    expected_columns = {
        "lifecycle_event_id",
        "instrument_id",
        "event_type",
        "event_date",
        "symbol",
        "provider_symbol",
        "source",
        "event_key",
        "details",
        "created_at",
        "updated_at",
    }
    assert expected_columns == set(instrument_lifecycle_event.c.keys())
    assert {"source", "event_key"} in [
        set(constraint.columns.keys()) for constraint in instrument_lifecycle_event.constraints
    ]


def test_market_calendar_has_daily_us_calendar_columns() -> None:
    assert {
        "calendar_id",
        "calendar_date",
        "is_trading_day",
        "source",
        "created_at",
        "updated_at",
    } == set(market_calendar.c.keys())
    assert {"calendar_date"} in [
        set(constraint.columns.keys()) for constraint in market_calendar.constraints
    ]


def test_quality_issue_records_issue_identity_and_resolution_state() -> None:
    expected_columns = {
        "issue_type",
        "severity",
        "instrument_id",
        "symbol",
        "trade_date",
        "details",
        "status",
        "resolved_at",
    }
    assert expected_columns.issubset(data_quality_issue.c.keys())


def test_quarantine_tables_archive_daily_price_payloads() -> None:
    assert {
        "quarantine_plan_id",
        "issue_id",
        "action_type",
        "target_schema",
        "target_table",
        "instrument_id",
        "date_from",
        "date_to",
        "status",
        "row_count",
    }.issubset(quarantine_plan.c.keys())
    assert {"issue_id", "action_type"} in [
        set(constraint.columns.keys()) for constraint in quarantine_plan.constraints
    ]
    assert {
        "quarantined_row_id",
        "quarantine_plan_id",
        "issue_id",
        "source_primary_key",
        "row_payload",
        "row_hash",
        "quarantine_reason",
    }.issubset(quarantined_daily_price_row.c.keys())

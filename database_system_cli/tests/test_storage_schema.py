from fdp.storage import (
    SYSTEM_SCHEMA,
    US_SHARE_SCHEMA,
    bulk_unmatched_daily_price_observation,
    corporate_action,
    crypto_daily_price,
    DAILY_PRICE_TABLES,
    data_quality_issue,
    etf_daily_price,
    etf_instrument,
    forex_daily_price,
    fund_daily_price,
    fund_daily_price_split_run,
    fund_instrument,
    identifier_mapping_unmatched_observation,
    index_daily_price,
    index_instrument,
    ingestion_task_run,
    ingestion_task_work_unit,
    instrument,
    instrument_identifier_history,
    instrument_identity_resolution_audit,
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
    assert f"{US_SHARE_SCHEMA}.fund_instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.index_instrument" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.instrument_identifier_history" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.instrument_lifecycle_event" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.stock_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.etf_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.fund_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.index_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.forex_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.crypto_daily_price" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.market_calendar" in metadata.tables
    assert f"{US_SHARE_SCHEMA}.corporate_action" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.data_quality_issue" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.repair_plan" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.quarantine_plan" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.quarantined_daily_price_row" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.bulk_unmatched_daily_price_observation" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.identifier_mapping_unmatched_observation" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.instrument_identity_resolution_audit" in metadata.tables
    assert f"{SYSTEM_SCHEMA}.fund_daily_price_split_run" in metadata.tables
    assert fund_daily_price_split_run.schema == SYSTEM_SCHEMA


def test_fund_split_run_tracks_resumable_compact_swap_state() -> None:
    assert {
        "finalize_strategy",
        "rows_compacted",
        "compact_last_source_id",
        "compact_verification_fingerprint",
        "compact_verification_details",
        "compact_verified_at",
        "swapped_at",
    }.issubset(fund_daily_price_split_run.c.keys())


def test_instrument_keeps_standard_and_provider_symbols() -> None:
    assert instrument.schema == US_SHARE_SCHEMA
    assert "symbol" in instrument.c
    assert "provider_symbol" in instrument.c
    assert {"provider", "provider_symbol"} in [
        set(constraint.columns.keys()) for constraint in instrument.constraints
    ]


def test_asset_daily_price_tables_have_instrument_date_uniqueness() -> None:
    assert set(DAILY_PRICE_TABLES) == {"stock", "etf", "fund", "index", "forex", "crypto"}
    for price_table in (
        stock_daily_price,
        etf_daily_price,
        fund_daily_price,
        index_daily_price,
        forex_daily_price,
        crypto_daily_price,
    ):
        assert "symbol" in price_table.c
        assert "provider_symbol" in price_table.c
        assert {"instrument_id", "trade_date"} in [
            set(constraint.columns.keys()) for constraint in price_table.constraints
        ]


def test_asset_instrument_views_are_read_handles() -> None:
    for view in (stock_instrument, etf_instrument, fund_instrument, index_instrument):
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
        "valid_from_key",
        "valid_to",
        "source",
        "created_at",
        "updated_at",
    }
    assert expected_columns.issubset(instrument_identifier_history.c.keys())
    assert {"instrument_id", "id_type", "id_value", "valid_from_key", "source"} in [
        set(constraint.columns.keys()) for constraint in instrument_identifier_history.constraints
    ]
    assert "ix_identifier_history_instrument" in {
        index.name for index in instrument_identifier_history.indexes
    }


def test_identifier_mapping_unmatched_observation_preserves_reconciliation_evidence() -> None:
    expected_columns = {
        "observation_id",
        "last_run_id",
        "market",
        "provider_symbol",
        "isin",
        "figi",
        "lei",
        "cusip",
        "cik",
        "raw_payload",
        "mapping_fingerprint",
        "reason",
        "candidate_instrument_ids",
        "resolution_status",
        "resolved_instrument_id",
        "source",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
        "created_at",
        "updated_at",
    }

    assert expected_columns == set(identifier_mapping_unmatched_observation.c.keys())
    assert {"source", "mapping_fingerprint"} in [
        set(constraint.columns.keys())
        for constraint in identifier_mapping_unmatched_observation.constraints
    ]


def test_guided_reconcile_storage_tracks_checkpoint_and_identity_evidence() -> None:
    assert "checkpoint_json" in ingestion_task_run.c
    assert "last_classified_run_id" in bulk_unmatched_daily_price_observation.c
    assert {
        "audit_id",
        "instrument_id",
        "provider_symbol",
        "market",
        "source",
        "match_method",
        "confidence",
        "evidence_type",
        "resolver_version",
        "observed_from",
        "observed_to",
        "first_run_id",
        "last_run_id",
        "reason",
        "supersedes_audit_id",
        "created_at",
        "updated_at",
    } == set(instrument_identity_resolution_audit.c.keys())
    assert {
        "instrument_id",
        "provider_symbol",
        "market",
        "source",
        "match_method",
        "confidence",
        "evidence_type",
        "resolver_version",
    } in [
        set(constraint.columns.keys())
        for constraint in instrument_identity_resolution_audit.constraints
    ]
    assert "ix_bulk_unmatched_market_status_date_id" in {
        index.name for index in bulk_unmatched_daily_price_observation.indexes
    }


def test_daily_task_storage_tracks_identity_lease_and_per_date_evidence() -> None:
    assert {
        "task_fingerprint",
        "active_resume_key",
        "workflow_version",
        "supersedes_run_id",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
    }.issubset(ingestion_task_run.c.keys())
    assert {
        "work_unit_id",
        "run_id",
        "unit_key",
        "unit_fingerprint",
        "series_fingerprint",
        "status",
        "reused_from_work_unit_id",
        "rows_fetched",
        "rows_published",
        "rows_pending",
        "rows_rejected",
        "api_calls",
        "api_units",
        "response_hash",
        "quality_status",
        "metrics_json",
    }.issubset(ingestion_task_work_unit.c.keys())


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


def test_corporate_action_preserves_provider_event_details() -> None:
    assert {
        "corporate_action_id",
        "instrument_id",
        "symbol",
        "provider_symbol",
        "action_type",
        "action_date",
        "declaration_date",
        "record_date",
        "payment_date",
        "period",
        "cash_amount",
        "unadjusted_cash_amount",
        "currency",
        "split_ratio",
        "split_numerator",
        "split_denominator",
        "source",
        "created_at",
        "updated_at",
    } == set(corporate_action.c.keys())
    assert {"instrument_id", "action_type", "action_date", "source"} in [
        set(constraint.columns.keys()) for constraint in corporate_action.constraints
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


def test_bulk_unmatched_observation_preserves_raw_rows_for_classification() -> None:
    expected_columns = {
        "observation_id",
        "run_id",
        "market",
        "exchange",
        "provider_symbol",
        "symbol",
        "trade_date",
        "eodhd_type",
        "raw_payload",
        "classification_status",
        "classified_asset_type",
        "matched_instrument_id",
        "reason",
        "source",
    }
    assert expected_columns.issubset(bulk_unmatched_daily_price_observation.c.keys())
    assert {"source", "provider_symbol", "trade_date"} in [
        set(constraint.columns.keys())
        for constraint in bulk_unmatched_daily_price_observation.constraints
    ]

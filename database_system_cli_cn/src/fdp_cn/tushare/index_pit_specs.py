"""Closed provider contracts used by the index-history and PIT workflow."""

from __future__ import annotations

from fdp_cn.tushare.models import (
    AccessSpec,
    CapabilitySpec,
    EndpointSpec,
    FanoutSpec,
    PaginationSpec,
    ParameterSpec,
)


_STANDARD_ACCESS = AccessSpec(
    "standard_points",
    "Available to the configured 10,000-point Tushare account.",
    points_tier=10_000,
)
_EXECUTABLE = CapabilitySpec("executable")


def _column_types(
    *,
    text: tuple[str, ...] = (),
    dates: tuple[str, ...] = (),
    decimals: tuple[str, ...] = (),
) -> dict[str, str]:
    return {
        **{name: "text" for name in text},
        **{name: "date" for name in dates},
        **{name: "decimal" for name in decimals},
    }


INDEX_BASIC_FIELDS = (
    "ts_code",
    "name",
    "market",
    "publisher",
    "category",
    "base_date",
    "base_point",
    "list_date",
    "fullname",
    "index_type",
    "weight_rule",
    "desc",
    "exp_date",
)
INDEX_CLASSIFY_FIELDS = (
    "index_code",
    "industry_name",
    "parent_code",
    "level",
    "industry_code",
    "is_pub",
    "src",
)
SW_DAILY_DECIMALS = (
    "open",
    "low",
    "high",
    "close",
    "change",
    "pct_change",
    "vol",
    "amount",
    "pe",
    "pb",
    "float_mv",
    "total_mv",
)
INDEX_MEMBER_FIELDS = (
    "index_code",
    "con_code",
    "in_date",
    "out_date",
    "is_new",
)
INDEX_MEMBER_ALL_FIELDS = (
    "l1_code",
    "l1_name",
    "l2_code",
    "l2_name",
    "l3_code",
    "l3_name",
    "ts_code",
    "name",
    "in_date",
    "out_date",
    "is_new",
)
INDEX_WEIGHT_FIELDS = ("index_code", "con_code", "trade_date", "weight")


INDEX_BASIC_SPEC = EndpointSpec(
    key="index_pit.index_basic",
    legacy_id="get_ph_data_from_ts.idx.Get_idx_basic.get_idx_basic",
    aliases=(),
    category="idx",
    api_name="index_basic",
    target_table="hq_idx_basic",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit",
        8_000,
        "https://tushare.pro/document/2?doc_id=94",
    ),
    scope_kind="single",
    business_key=("ts_code",),
    fields=INDEX_BASIC_FIELDS,
    column_types=_column_types(
        text=tuple(
            name
            for name in INDEX_BASIC_FIELDS
            if name not in {"base_date", "base_point", "list_date"}
        ),
        dates=("base_date", "list_date"),
        decimals=("base_point",),
    ),
    text_min_lengths={
        "ts_code": 20,
        "name": 250,
        "market": 20,
        "publisher": 250,
        "category": 50,
        "fullname": 200,
        "index_type": 50,
        "weight_rule": 100,
        "desc": 200,
        "exp_date": 8,
    },
    nullable_columns=frozenset(
        {
            "base_date",
            "base_point",
            "list_date",
            "fullname",
            "index_type",
            "weight_rule",
            "desc",
            "exp_date",
        }
    ),
    request_params={
        "ts_code": ParameterSpec("text"),
        "name": ParameterSpec("text"),
        "market": ParameterSpec("text"),
        "publisher": ParameterSpec("text"),
        "category": ParameterSpec("text"),
    },
    official_url="https://tushare.pro/document/2?doc_id=94",
    reviewed_on="2026-08-24",
    description="指数基础信息",
)

INDEX_CLASSIFY_SPEC = EndpointSpec(
    key="index_pit.index_classify",
    legacy_id="get_ph_data_from_ts.idx.Get_idx_sw_classify.get_idx_sw_classify",
    aliases=(),
    category="idx",
    api_name="index_classify",
    target_table="hq_idx_sw_classify",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit_probe",
        10_000,
        "https://tushare.pro/document/2?doc_id=181",
    ),
    scope_kind="single",
    business_key=("src", "level", "index_code"),
    fields=INDEX_CLASSIFY_FIELDS,
    column_types=_column_types(text=INDEX_CLASSIFY_FIELDS),
    text_min_lengths={name: 20 for name in INDEX_CLASSIFY_FIELDS},
    nullable_columns=frozenset({"parent_code", "industry_code", "is_pub"}),
    fanouts=(
        FanoutSpec("src", ("SW2014", "SW2021")),
        FanoutSpec("level", ("L1", "L2", "L3")),
    ),
    official_url="https://tushare.pro/document/2?doc_id=181",
    reviewed_on="2026-08-24",
    description="申万 2014/2021 行业分类",
)

SW_DAILY_SPEC = EndpointSpec(
    key="index_pit.sw_daily",
    legacy_id="get_ph_data_from_ts.idx.Get_idx_sw_daily.get_idx_sw_daily",
    aliases=(),
    category="idx",
    api_name="sw_daily",
    target_table="hq_idx_sw_daily",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit",
        4_000,
        "https://tushare.pro/document/2?doc_id=327",
    ),
    scope_kind="date_range",
    business_key=("trade_date", "ts_code"),
    fields=("ts_code", "trade_date", "name", *SW_DAILY_DECIMALS),
    column_types=_column_types(
        text=("ts_code", "name"),
        dates=("trade_date",),
        decimals=SW_DAILY_DECIMALS,
    ),
    text_min_lengths={"ts_code": 20, "name": 200},
    # Tushare can retain a valid index/date row while all quote and turnover
    # values are unavailable (observed for 801863.SI on 2013-10-23).
    nullable_columns=frozenset(SW_DAILY_DECIMALS),
    request_params={
        "ts_code": ParameterSpec("text"),
        "trade_date": ParameterSpec("date"),
        "start_date": ParameterSpec("date"),
        "end_date": ParameterSpec("date"),
    },
    official_url="https://tushare.pro/document/2?doc_id=327",
    reviewed_on="2026-08-24",
    description="申万行业日线",
)

INDEX_MEMBER_SPEC = EndpointSpec(
    key="index_pit.index_member_sw2014",
    legacy_id="get_ph_data_from_ts.idx.Get_idx_sw_member.get_idx_sw_member",
    aliases=(),
    category="idx",
    api_name="index_member",
    target_table="hq_idx_sw_member",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit",
        2_000,
        "https://tushare.pro/document/2?doc_id=182",
    ),
    scope_kind="single",
    business_key=("index_code", "con_code", "in_date"),
    fields=INDEX_MEMBER_FIELDS,
    column_types=_column_types(
        text=("index_code", "con_code", "is_new"),
        dates=("in_date", "out_date"),
    ),
    text_min_lengths={"index_code": 20, "con_code": 20, "is_new": 20},
    nullable_columns=frozenset({"out_date"}),
    request_params={
        "index_code": ParameterSpec("text", required=True),
        "is_new": ParameterSpec("choice", choices=("Y", "N")),
    },
    official_url="https://tushare.pro/document/2?doc_id=182",
    reviewed_on="2026-08-24",
    description="申万 2014 扁平成员区间",
)

INDEX_MEMBER_ALL_SPEC = EndpointSpec(
    key="index_pit.index_member_all_sw2021",
    legacy_id="get_ph_data_from_ts.idx.Get_idx_sw_member_all.get_idx_sw_member_all",
    aliases=(),
    category="idx",
    api_name="index_member_all",
    target_table="hq_idx_sw_member_all",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit",
        2_000,
        "https://tushare.pro/document/2?doc_id=335",
    ),
    scope_kind="single",
    business_key=("ts_code", "l1_code", "l2_code", "l3_code", "in_date"),
    fields=INDEX_MEMBER_ALL_FIELDS,
    column_types=_column_types(
        text=(
            "l1_code",
            "l1_name",
            "l2_code",
            "l2_name",
            "l3_code",
            "l3_name",
            "ts_code",
            "name",
            "is_new",
        ),
        dates=("in_date", "out_date"),
    ),
    text_min_lengths={
        "l1_code": 20,
        "l1_name": 50,
        "l2_code": 20,
        "l2_name": 50,
        "l3_code": 20,
        "l3_name": 50,
        "ts_code": 20,
        "name": 50,
        "is_new": 2,
    },
    nullable_columns=frozenset({"out_date"}),
    request_params={
        "l1_code": ParameterSpec("text", required=True),
        "is_new": ParameterSpec("choice", choices=("Y", "N")),
    },
    official_url="https://tushare.pro/document/2?doc_id=335",
    reviewed_on="2026-08-24",
    description="申万 2021 分级成员区间",
)

INDEX_WEIGHT_SPEC = EndpointSpec(
    key="index_pit.index_weight",
    legacy_id="index_weight",
    aliases=(),
    category="idx",
    api_name="index_weight",
    target_table="idx_member_pit",
    access=_STANDARD_ACCESS,
    capability=_EXECUTABLE,
    pagination=PaginationSpec(
        "offset_limit",
        5_000,
        "J21 probe; the official page recommends one natural month per request but does not publish a numeric page limit",
    ),
    scope_kind="date_range",
    business_key=("trade_date", "index_code", "con_code"),
    fields=INDEX_WEIGHT_FIELDS,
    column_types=_column_types(
        text=("index_code", "con_code"),
        dates=("trade_date",),
        decimals=("weight",),
    ),
    text_min_lengths={"index_code": 20, "con_code": 20},
    nullable_columns=frozenset(),
    request_params={
        "index_code": ParameterSpec("text", required=True),
        "start_date": ParameterSpec("date", required=True),
        "end_date": ParameterSpec("date", required=True),
    },
    official_url="https://tushare.pro/document/2?doc_id=96",
    reviewed_on="2026-08-24",
    description="指数月度成分权重快照",
)

SOURCE_SPECS = (
    INDEX_BASIC_SPEC,
    INDEX_CLASSIFY_SPEC,
    SW_DAILY_SPEC,
    INDEX_MEMBER_SPEC,
    INDEX_MEMBER_ALL_SPEC,
)

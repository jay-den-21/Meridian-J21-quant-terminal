"""Typed contracts shared by the Tushare source layer.

The source package deliberately owns provider-shaped data only.  Jobs decide
which endpoints to run and transactions decide when a page is committed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
RequestScalar: TypeAlias = str | int | Decimal | bool
ColumnKind: TypeAlias = Literal["text", "date", "decimal", "integer"]
ParameterKind: TypeAlias = Literal["text", "date", "integer", "decimal", "choice"]
CapabilityKind: TypeAlias = Literal[
    "executable",
    "catalogued_not_implemented",
    "disabled_realtime",
    "disabled_unsupported",
]
AccessKind: TypeAlias = Literal[
    "standard_points",
    "separate_purchase",
    "external_realtime",
]
PaginationKind: TypeAlias = Literal[
    "offset_limit",
    "offset_limit_probe",
    "undocumented",
    "not_applicable",
]
ScopeKind: TypeAlias = Literal[
    "single",
    "date_range",
    "code_list",
    "code_date_range",
    "realtime",
]
TushareApiEventKind: TypeAlias = Literal["request", "retry", "success", "failed"]


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class AccessSpec:
    """How an endpoint is licensed by the provider.

    ``points_tier`` is the reviewed account tier at which J21 classified a
    standard-points endpoint as available.  It is deliberately not presented
    as the provider's exact minimum-points requirement.
    """

    kind: AccessKind
    reason: str
    points_tier: int | None

    def __post_init__(self) -> None:
        if self.kind not in {
            "standard_points",
            "separate_purchase",
            "external_realtime",
        }:
            raise ValueError(f"unsupported access kind: {self.kind}")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("access reason must be non-empty text")
        if self.kind == "standard_points":
            if (
                isinstance(self.points_tier, bool)
                or not isinstance(self.points_tier, int)
                or self.points_tier <= 0
            ):
                raise ValueError(
                    "standard-points access requires a positive integer points tier"
                )
        elif self.points_tier is not None:
            raise ValueError("non-standard access must not declare a points tier")


@dataclass(frozen=True)
class CapabilitySpec:
    """Whether J21 can execute an endpoint in this release."""

    kind: CapabilityKind
    reason: str | None = None


@dataclass(frozen=True)
class PaginationSpec:
    """Provider pagination contract captured from reviewed documentation."""

    kind: PaginationKind
    page_limit: int | None
    source: str

    def __post_init__(self) -> None:
        paginated = self.kind in {"offset_limit", "offset_limit_probe"}
        if paginated != (self.page_limit is not None):
            raise ValueError("paginated endpoints require one positive page limit")
        if self.page_limit is not None and self.page_limit <= 0:
            raise ValueError("page_limit must be positive")


@dataclass(frozen=True)
class ParameterSpec:
    """One caller-controlled provider parameter."""

    kind: ParameterKind
    required: bool = False
    choices: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "choice" and not self.choices:
            raise ValueError("choice parameters require choices")
        if self.kind != "choice" and self.choices:
            raise ValueError("only choice parameters may declare choices")


@dataclass(frozen=True)
class FanoutSpec:
    """A deterministic provider fan-out owned by one endpoint."""

    parameter: str
    values: tuple[str, ...]
    fixed_params: Mapping[str, RequestScalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parameter or not self.values:
            raise ValueError("fanout requires a parameter and at least one value")
        if len(set(self.values)) != len(self.values):
            raise ValueError("fanout values must be unique")
        object.__setattr__(self, "fixed_params", _freeze_mapping(self.fixed_params))


@dataclass(frozen=True)
class EndpointSpec:
    """Closed runtime contract for one catalogued endpoint variant."""

    key: str
    legacy_id: str
    aliases: tuple[str, ...]
    category: str
    api_name: str
    target_table: str
    access: AccessSpec
    capability: CapabilitySpec
    pagination: PaginationSpec
    scope_kind: ScopeKind
    business_key: tuple[str, ...]
    fields: tuple[str, ...] = ()
    column_types: Mapping[str, ColumnKind] = field(default_factory=dict)
    text_min_lengths: Mapping[str, int] = field(default_factory=dict)
    nullable_columns: frozenset[str] = frozenset()
    field_aliases: Mapping[str, str] = field(default_factory=dict)
    request_params: Mapping[str, ParameterSpec] = field(default_factory=dict)
    fixed_params: Mapping[str, RequestScalar] = field(default_factory=dict)
    fanouts: tuple[FanoutSpec, ...] = ()
    prerequisites: tuple[str, ...] = ()
    official_url: str | None = None
    reviewed_on: str | None = None
    description: str = ""
    legacy_path: str = ""
    legacy_profile: str = ""
    required_inputs: tuple[str, ...] = ()
    frequency: str | None = None
    source_variant: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "column_types", _freeze_mapping(self.column_types))
        object.__setattr__(
            self, "text_min_lengths", _freeze_mapping(self.text_min_lengths)
        )
        object.__setattr__(self, "field_aliases", _freeze_mapping(self.field_aliases))
        object.__setattr__(self, "request_params", _freeze_mapping(self.request_params))
        object.__setattr__(self, "fixed_params", _freeze_mapping(self.fixed_params))

    @property
    def executable(self) -> bool:
        return self.capability.kind == "executable"

    @property
    def table(self) -> str:
        """Compatibility spelling used by storage callers."""
        return self.target_table

    @property
    def page_limit(self) -> int | None:
        return self.pagination.page_limit

    @property
    def endpoint(self) -> str:
        return self.api_name

    @property
    def profile(self) -> str:
        return self.legacy_profile

    @property
    def freq(self) -> str | None:
        return self.frequency

    @property
    def src(self) -> str | None:
        return self.source_variant


@dataclass(frozen=True)
class EndpointPlanRequest:
    """Caller scope before endpoint-local fan-out and pagination."""

    date_from: date | str | None = None
    date_to: date | str | None = None
    codes: tuple[str, ...] = ()
    params: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _freeze_mapping(self.params))


@dataclass(frozen=True)
class EndpointUnit:
    """One broad request scope; pagination advances only its offset."""

    endpoint_key: str
    scope_key: str
    params: Mapping[str, RequestScalar]
    page_limit: int

    def __post_init__(self) -> None:
        if self.page_limit <= 0:
            raise ValueError("page_limit must be positive")
        object.__setattr__(self, "params", _freeze_mapping(self.params))

    def page_request(self, spec: EndpointSpec, *, offset: int = 0) -> TushareRequest:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if spec.key != self.endpoint_key:
            raise ValueError("endpoint unit does not match endpoint spec")
        params = dict(self.params)
        params.update({"limit": self.page_limit, "offset": offset})
        return TushareRequest(
            endpoint_key=spec.key,
            api_name=spec.api_name,
            params=params,
            fields=spec.fields,
        )


@dataclass(frozen=True)
class TushareRequest:
    """One exact POST request to the fixed Tushare data API."""

    endpoint_key: str
    api_name: str
    params: Mapping[str, RequestScalar]
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.endpoint_key or not self.api_name:
            raise ValueError("endpoint_key and api_name must not be empty")
        object.__setattr__(self, "params", _freeze_mapping(self.params))


@dataclass(frozen=True)
class TushareResponse:
    """Validated provider response with audit-safe attempt metadata."""

    endpoint_key: str
    api_name: str
    fields: tuple[str, ...]
    items: tuple[tuple[JsonScalar, ...], ...]
    attempts: int
    status_code: int | None = 200
    provider_message: str = ""

    @property
    def rows_returned(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class TushareApiEvent:
    """Secret-safe transport event suitable for progress/audit adapters."""

    kind: TushareApiEventKind
    endpoint: str
    attempt: int
    max_attempts: int
    status_code: int | None = None
    rows_returned: int | None = None
    duration_ms: int | None = None
    error_kind: str | None = None
    error_message: str | None = None
    retry_delay_seconds: float | None = None


@dataclass(frozen=True)
class CleanedPage:
    """Normalized, exact-deduplicated rows ready for one page transaction."""

    endpoint_key: str
    fetched_rows: int
    rows: tuple[Mapping[str, object], ...]

    @property
    def cleaned_rows(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class ExternalTableContract:
    """Verified facts about one externally owned ``a_share`` table."""

    schema: str
    table: str
    columns: tuple[str, ...]
    identity_column: str
    business_key: tuple[str, ...]
    supporting_index: tuple[str, ...]


@dataclass(frozen=True)
class TusharePageWriteResult:
    """Deterministic counts from one atomic page write."""

    input_rows: int
    inserted_rows: int
    updated_rows: int

    @property
    def written_rows(self) -> int:
        return self.inserted_rows + self.updated_rows
